"""Turns an alignment into per-note classifications and a summary score.

Sub-score formulas (all 0-100):
  pitch accuracy    = (correct+timing_off) / (correct+timing_off+wrong_pitch+missed+extra) * 100
                       -- fraction of the performance that landed on the right pitch at all.
  rhythm accuracy   = correct / (correct+timing_off) * 100
                       -- of the notes played with the right pitch, % within tolerance.
  timing stability  = 100 / (1 + std(offset_ms) / tol_ms)
                       -- 100 at std=0, 50 at std=tol_ms, asymptotic to 0 as std grows.
  overall           = score_weight_pitch*pitch + score_weight_rhythm*rhythm
                       + score_weight_timing_stability*timing_stability   (weights in ScoringConfig)
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from . import align as _align
from .config import ScoringConfig
from .models import NoteResult, ScoringResult, ScoringSummary, midi_pitch_to_name

try:
    from backend.score_to_reference import to_seconds
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "backend.scoring depends on backend.score_to_reference -- run commands "
        "from the repository root or add the repository root to PYTHONPATH."
    ) from exc


def score_performance(
    reference: dict,
    performance: list,
    config: Optional[ScoringConfig] = None,
    target_bpm: Optional[int] = None,
) -> ScoringResult:
    """Score a symbolic performance against a score_to_reference JSON reference.

    If `target_bpm` is given, the reference is first rescaled to that BPM
    (via backend.score_to_reference.to_seconds) and residuals are absolute -- we trust
    that the performer intended that exact tempo. Otherwise a robust
    piecewise-linear tempo curve is fit from confidently-matched notes (see
    align.fit_tempo_curve) -- this absorbs both a uniform tempo difference
    and genuine local tempo changes (rubato, a sustained mid-piece speed-up),
    so a performance that is consistently fast/slow, or changes pace in one
    section, is not flagged as rush/drag everywhere. `global_tempo_ratio` in
    the summary reports the single overall robust-fit slope, for reference --
    the actual per-note residuals used for classification come from the
    curve, not that single number.
    """
    config = config or ScoringConfig()

    if target_bpm is not None:
        reference = to_seconds(reference, target_bpm)

    ref_notes = reference["notes"]
    perf_notes = performance

    ref_onsets_raw = [n["onset_sec"] for n in ref_notes]
    ref_pitches_raw = [n["pitch"] for n in ref_notes]
    perf_onsets_raw = [n["onset_sec"] for n in perf_notes]
    perf_pitches_raw = [n["pitch"] for n in perf_notes]

    ref_onsets, ref_pitches, ref_orig_idx = _align.prepare_sequence(
        ref_onsets_raw, ref_pitches_raw, config.chord_window_sec
    )
    perf_onsets, perf_pitches, perf_orig_idx = _align.prepare_sequence(
        perf_onsets_raw, perf_pitches_raw, config.chord_window_sec
    )

    if target_bpm is not None:
        tempo_curve = _align.TempoCurve(np.array([0.0, 1.0]), np.array([0.0, 1.0]), 1.0)
        global_tempo_ratio = None
    else:
        tempo_curve = _align.fit_tempo_curve(
            ref_onsets, ref_pitches, perf_onsets, perf_pitches, config
        )
        global_tempo_ratio = tempo_curve.representative_slope

    pairs = _align.align_notes(
        ref_onsets, ref_pitches, perf_onsets, perf_pitches, config, tempo_curve
    )

    bpm_for_tol = target_bpm if target_bpm is not None else reference.get("tempo_bpm", 120)
    tol_ms = config.effective_tol_ms(bpm_for_tol)

    note_results = []
    for pos_ref, pos_perf in pairs:
        ref_idx = ref_orig_idx[pos_ref] if pos_ref is not None else None
        perf_idx = perf_orig_idx[pos_perf] if pos_perf is not None else None
        ref_note = ref_notes[ref_idx] if ref_idx is not None else None
        perf_note = perf_notes[perf_idx] if perf_idx is not None else None

        if ref_note is not None and perf_note is not None:
            predicted = tempo_curve.predict(ref_note["onset_sec"])
            offset_ms = (perf_note["onset_sec"] - predicted) * 1000.0
            if ref_note["pitch"] != perf_note["pitch"]:
                status = "wrong_pitch"
            elif abs(offset_ms) <= tol_ms:
                status = "correct"
            else:
                status = "timing_off"
            timing = "accurate" if abs(offset_ms) <= tol_ms else ("rush" if offset_ms < 0 else "drag")
            note_results.append(NoteResult(
                ref_index=ref_idx, perf_index=perf_idx,
                pitch_ref=ref_note["pitch"], pitch_perf=perf_note["pitch"],
                name=ref_note.get("name"),
                onset_ref_sec=ref_note["onset_sec"], onset_perf_sec=perf_note["onset_sec"],
                offset_ms=offset_ms, status=status, timing=timing,
                measure=ref_note.get("measure"), hand=ref_note.get("hand"),
                dur_beats=ref_note.get("dur_beats"),
            ))
        elif ref_note is not None:
            note_results.append(NoteResult(
                ref_index=ref_idx, perf_index=None,
                pitch_ref=ref_note["pitch"], pitch_perf=None,
                name=ref_note.get("name"),
                onset_ref_sec=ref_note["onset_sec"], onset_perf_sec=None,
                offset_ms=None, status="missed", timing=None,
                measure=ref_note.get("measure"), hand=ref_note.get("hand"),
                dur_beats=ref_note.get("dur_beats"),
            ))
        else:
            note_results.append(NoteResult(
                ref_index=None, perf_index=perf_idx,
                pitch_ref=None, pitch_perf=perf_note["pitch"],
                name=midi_pitch_to_name(perf_note["pitch"]),
                onset_ref_sec=None, onset_perf_sec=perf_note["onset_sec"],
                offset_ms=None, status="extra", timing=None,
                measure=None, hand=None,
            ))

    summary = _summarize(note_results, config, global_tempo_ratio)
    return ScoringResult(summary=summary, notes=note_results)


def _summarize(note_results: list, config: ScoringConfig, global_tempo_ratio) -> ScoringSummary:
    counts = {"correct": 0, "timing_off": 0, "wrong_pitch": 0, "missed": 0, "extra": 0}
    for r in note_results:
        counts[r.status] += 1

    denom_all = sum(counts.values())
    pitch_accuracy = (
        100.0 * (counts["correct"] + counts["timing_off"]) / denom_all if denom_all else 100.0
    )

    matched_pitch_ok = counts["correct"] + counts["timing_off"]
    rhythm_accuracy = 100.0 * counts["correct"] / matched_pitch_ok if matched_pitch_ok else 100.0

    offsets = [r.offset_ms for r in note_results if r.offset_ms is not None]
    std_ms = float(np.std(offsets)) if offsets else 0.0
    timing_stability = 100.0 / (1.0 + std_ms / config.tol_ms)

    overall = (
        config.score_weight_pitch * pitch_accuracy
        + config.score_weight_rhythm * rhythm_accuracy
        + config.score_weight_timing_stability * timing_stability
    )

    return ScoringSummary(
        score=round(overall, 2),
        sub_scores={
            "pitch": round(pitch_accuracy, 2),
            "rhythm": round(rhythm_accuracy, 2),
            "timing_stability": round(timing_stability, 2),
        },
        global_tempo_ratio=round(global_tempo_ratio, 4) if global_tempo_ratio is not None else None,
        tempo_trend=_tempo_trend(note_results, config),
        counts=counts,
    )


def _tempo_trend(note_results: list, config: ScoringConfig) -> str:
    """Linear-regress offset_ms against note index (matched notes only, in
    order). A negative slope means notes drift increasingly *early* as the
    piece goes on -- the performer sped up ("accelerating"); positive means
    they slowed down ("decelerating"); anything under
    tempo_trend_min_slope_ms is "steady".
    """
    xs, ys = [], []
    for idx, r in enumerate(note_results):
        if r.offset_ms is not None:
            xs.append(idx)
            ys.append(r.offset_ms)
    if len(xs) < 2:
        return "steady"
    slope = float(np.polyfit(xs, ys, 1)[0])
    if slope <= -config.tempo_trend_min_slope_ms:
        return "accelerating"
    if slope >= config.tempo_trend_min_slope_ms:
        return "decelerating"
    return "steady"
