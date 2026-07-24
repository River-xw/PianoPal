"""Turns an alignment into per-note classifications and a summary score.

Sub-score formulas (all 0-100):
  pitch accuracy    = (correct+timing_off) / (correct+timing_off+wrong_pitch+missed+extra) * 100
                       -- fraction of the performance that landed on the right pitch at all.
  rhythm accuracy   = pitch_accuracy * correct / (correct+timing_off)
                       -- coverage-adjusted: missing most notes cannot still score 100 rhythm.
  timing stability  = pitch_accuracy * raw_timing_stability / 100
                       -- coverage-adjusted: a few perfectly-aligned notes cannot hide many misses.
  overall           = weighted average of every available sub-score.
                       A requested external score such as hand posture can be
                       unavailable; in that case the remaining weights are
                       renormalized instead of silently treating it as zero.
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
    song_name: Optional[str] = None,
    hand_shape_score: Optional[float] = None,
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

    `song_name` is stored on the result for display (e.g. in the viewer)
    and defaults to the reference's own `title` field if not given.

    `hand_shape_score` (0-100) is an externally-supplied posture/hand-shape
    score -- this module has no sensor input of its own. Only used when
    config.score_weight_hand_shape > 0; otherwise ignored, matching how
    score_weight_timing_stability=0 fully excludes that sub-score too.
    """
    config = config or ScoringConfig()
    song_name = song_name if song_name is not None else reference.get("title")

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

    harmonic_extras_removed = 0
    if config.suppress_harmonic_extras:
        note_results, harmonic_extras_removed = _suppress_harmonic_extras(note_results, config)

    summary = _summarize(note_results, config, global_tempo_ratio, tol_ms, hand_shape_score)
    summary.harmonic_extras_removed = harmonic_extras_removed
    return ScoringResult(summary=summary, notes=note_results, song_name=song_name)


def _suppress_harmonic_extras(note_results: list, config: ScoringConfig) -> tuple:
    """Reference-aware overtone-artifact filter. Removes a note classified
    `extra` when it coincides in performance time with a matched
    (correct/timing_off) note a strong harmonic interval BELOW it -- i.e. it
    looks like an overtone of a genuinely-played note, and having reached the
    `extra` bucket means the reference confirms nothing was expected there.

    Structurally can only touch `extra` notes -- a real octave in the
    arrangement would be a reference note and align as `correct`, out of
    reach here. That's the whole point: the reference-FREE velocity filter
    (audio_to_performance/postprocess.py) deletes real notes because it can't
    make that distinction; this can't, because alignment already did.

    Returns (kept_note_results, removed_count). Does not mutate the input.
    """
    matched = [
        r for r in note_results
        if r.status in ("correct", "timing_off") and r.onset_perf_sec is not None
    ]
    window = config.harmonic_extra_window_sec
    intervals = config.harmonic_extra_intervals

    kept, removed = [], 0
    for r in note_results:
        if r.status == "extra" and r.pitch_perf is not None and r.onset_perf_sec is not None:
            is_artifact = any(
                abs(m.onset_perf_sec - r.onset_perf_sec) <= window
                and (r.pitch_perf - m.pitch_perf) in intervals  # extra strictly ABOVE = overtone
                for m in matched
            )
            if is_artifact:
                removed += 1
                continue
        kept.append(r)
    return kept, removed


def _summarize(
    note_results: list, config: ScoringConfig, global_tempo_ratio, tol_ms: float,
    hand_shape_score: Optional[float] = None,
) -> ScoringSummary:
    counts = {"correct": 0, "timing_off": 0, "wrong_pitch": 0, "missed": 0, "extra": 0}
    for r in note_results:
        counts[r.status] += 1

    denom_all = sum(counts.values())
    pitch_accuracy = (
        100.0 * (counts["correct"] + counts["timing_off"]) / denom_all if denom_all else 100.0
    )

    matched_pitch_ok = counts["correct"] + counts["timing_off"]
    raw_rhythm_accuracy = 100.0 * counts["correct"] / matched_pitch_ok if matched_pitch_ok else 0.0
    rhythm_accuracy = pitch_accuracy * (raw_rhythm_accuracy / 100.0)

    # A weight of 0 fully disables timing_stability -- not just excluded from
    # `overall`, but not computed/shown at all (None, not 0), since a caller
    # who set the weight to 0 has decided this sub-score isn't meaningful for
    # their use case (e.g. real mic recordings, where its std-of-offset_ms
    # basis is dominated by transcription/alignment noise, not genuine
    # unsteadiness) and showing a misleadingly-precise number would be worse
    # than admitting it's not tracked.
    if config.score_weight_timing_stability > 0:
        offsets = [r.offset_ms for r in note_results if r.offset_ms is not None]
        std_ms = float(np.std(offsets)) if offsets else 0.0
        raw_timing_stability = 100.0 / (1.0 + std_ms / tol_ms)
        timing_stability = pitch_accuracy * (raw_timing_stability / 100.0)
    else:
        timing_stability = None

    # Same on/off pattern as timing_stability above: weight 0 (the default,
    # since there's no production posture classifier feeding this yet) means
    # not computed/shown at all, not silently scored as 0.
    hand_shape = hand_shape_score if config.score_weight_hand_shape > 0 else None

    # External sensors are allowed to be unavailable. Do not turn a missing
    # posture score into either a fake perfect score or an implicit zero:
    # compute the weighted average across the sub-scores that were actually
    # measured. When every configured weight is present and weights sum to
    # one, this is identical to the original formula.
    weighted_scores = [
        (config.score_weight_pitch, pitch_accuracy),
        (config.score_weight_rhythm, rhythm_accuracy),
    ]
    if timing_stability is not None:
        weighted_scores.append((config.score_weight_timing_stability, timing_stability))
    if hand_shape is not None:
        weighted_scores.append((config.score_weight_hand_shape, hand_shape))
    available_weight = sum(weight for weight, _ in weighted_scores if weight > 0)
    overall = (
        sum(weight * value for weight, value in weighted_scores if weight > 0) / available_weight
        if available_weight > 0
        else 0.0
    )

    octave_slips = sum(
        1 for r in note_results
        if r.status == "wrong_pitch" and r.pitch_ref is not None and r.pitch_perf is not None
        and (r.pitch_ref - r.pitch_perf) % 12 == 0
    )

    return ScoringSummary(
        score=round(overall, 2),
        sub_scores={
            "pitch": round(pitch_accuracy, 2),
            "rhythm": round(rhythm_accuracy, 2),
            "timing_stability": round(timing_stability, 2) if timing_stability is not None else None,
            "hand_shape": round(hand_shape, 2) if hand_shape is not None else None,
        },
        global_tempo_ratio=round(global_tempo_ratio, 4) if global_tempo_ratio is not None else None,
        tempo_trend=_tempo_trend(note_results, config),
        counts=counts,
        octave_slips_in_wrong_pitch=octave_slips,
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
