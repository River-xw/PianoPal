"""Audio-to-audio practice references.

This path treats a trusted demo recording as the reference instead of requiring
an external MIDI file. Both the demo and the student's recording are converted
with the same lightweight electronic-keyboard event extractor, then compared by
the existing symbolic scorer.
"""
from __future__ import annotations

from typing import Optional

import librosa
import numpy as np

from backend.scoring.config import ScoringConfig
from backend.scoring.models import NoteResult, midi_pitch_to_name
from backend.scoring.score import _summarize, score_performance

from .reference_constrained import (
    ReferenceConstrainedConfig,
    _detect_audio_onsets,
    _pitch_scores_for_onset,
    transcribe_onset_first,
)


def extract_audio_events(
    audio,
    sr: int,
    config: Optional[ReferenceConstrainedConfig] = None,
) -> tuple[list, dict]:
    """Extract actual audio note events without Basic Pitch."""
    return transcribe_onset_first(audio, sr, config or ReferenceConstrainedConfig())


def extract_candidate_events(
    audio,
    sr: int,
    config: Optional[ReferenceConstrainedConfig] = None,
    top_k: int = 5,
) -> tuple[list, dict]:
    """Extract onset events with top-k pitch candidates."""
    config = config or ReferenceConstrainedConfig()
    events = []
    onset_times = _detect_audio_onsets(audio, sr, config)
    for onset_sec in onset_times:
        scores, total = _pitch_scores_for_onset(audio, sr, onset_sec, config)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
        confidence = float(ranked[0][1] / total) if ranked and total > 0 else 0.0
        if confidence < config.onset_min_confidence:
            continue
        events.append({
            "onset_sec": float(onset_sec),
            "pitch": int(ranked[0][0]),
            "confidence": confidence,
            "candidates": [
                {"pitch": int(pitch), "score": float(score)}
                for pitch, score in ranked
            ],
        })
    return events, {
        "mode": "candidate_events",
        "detected_onsets": len(onset_times),
        "events": len(events),
        "top_k": top_k,
    }


def events_to_reference(events: list, title: str = "Audio Demo Reference", tempo_bpm: int = 120) -> dict:
    """Convert extracted events into the reference JSON shape expected by scoring."""
    notes = []
    for idx, event in enumerate(sorted(events, key=lambda n: (n["onset_sec"], n["pitch"]))):
        onset_sec = float(event["onset_sec"])
        dur_sec = float(event.get("dur_sec", 0.18) or 0.18)
        notes.append({
            "pitch": int(event["pitch"]),
            "name": midi_pitch_to_name(int(event["pitch"])),
            "onset_beats": onset_sec * tempo_bpm / 60.0,
            "onset_sec": onset_sec,
            "dur_beats": dur_sec * tempo_bpm / 60.0,
            "dur_sec": dur_sec,
            "velocity": int(event.get("velocity", 80) or 80),
            "hand": "R",
            "measure": int((onset_sec * tempo_bpm / 60.0) // 4) + 1,
        })
    duration_sec = max((n["onset_sec"] + n["dur_sec"] for n in notes), default=0.0)
    return {
        "title": title,
        "tempo_bpm": tempo_bpm,
        "tempo_map": [{"beat": 0.0, "bpm": float(tempo_bpm)}],
        "time_signature": "4/4",
        "key": "unknown",
        "duration_beats": duration_sec * tempo_bpm / 60.0,
        "duration_sec": duration_sec,
        "notes": notes,
        "source": "audio_demo_extracted",
    }


def _candidate_pitch_distance(a: dict, b: dict, top_k: int = 5) -> int:
    a_pitches = [int(c["pitch"]) for c in a.get("candidates", [])[:top_k]] or [int(a["pitch"])]
    b_pitches = [int(c["pitch"]) for c in b.get("candidates", [])[:top_k]] or [int(b["pitch"])]
    return min(abs(pa - pb) for pa in a_pitches for pb in b_pitches)


def _best_shared_pitch(a: dict, b: dict, top_k: int = 5) -> Optional[int]:
    a_pitches = [int(c["pitch"]) for c in a.get("candidates", [])[:top_k]] or [int(a["pitch"])]
    b_pitches = [int(c["pitch"]) for c in b.get("candidates", [])[:top_k]] or [int(b["pitch"])]
    shared = [pitch for pitch in a_pitches if pitch in b_pitches]
    return shared[0] if shared else None


def _event_pair_cost(demo_event: dict, student_event: dict, demo_duration: float, student_duration: float) -> float:
    demo_pos = demo_event["onset_sec"] / demo_duration if demo_duration > 0 else 0.0
    student_pos = student_event["onset_sec"] / student_duration if student_duration > 0 else 0.0
    time_cost = abs(demo_pos - student_pos)
    pitch_distance = _candidate_pitch_distance(demo_event, student_event)
    pitch_cost = min(pitch_distance / 12.0, 1.0)
    return 1.6 * pitch_cost + 0.8 * time_cost


def _dtw_align_events(demo_events: list, student_events: list, gap_cost: float = 0.9) -> list:
    n, m = len(demo_events), len(student_events)
    demo_duration = max((e["onset_sec"] for e in demo_events), default=0.0)
    student_duration = max((e["onset_sec"] for e in student_events), default=0.0)
    dp = np.full((n + 1, m + 1), np.inf)
    back = [[None for _ in range(m + 1)] for _ in range(n + 1)]
    dp[0, 0] = 0.0
    for i in range(1, n + 1):
        dp[i, 0] = dp[i - 1, 0] + gap_cost
        back[i][0] = (i - 1, 0, "missed")
    for j in range(1, m + 1):
        dp[0, j] = dp[0, j - 1] + gap_cost
        back[0][j] = (0, j - 1, "extra")
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            pair_cost = _event_pair_cost(demo_events[i - 1], student_events[j - 1], demo_duration, student_duration)
            choices = [
                (dp[i - 1, j - 1] + pair_cost, i - 1, j - 1, "match"),
                (dp[i - 1, j] + gap_cost, i - 1, j, "missed"),
                (dp[i, j - 1] + gap_cost, i, j - 1, "extra"),
            ]
            best = min(choices, key=lambda item: item[0])
            dp[i, j] = best[0]
            back[i][j] = best[1:]

    pairs = []
    i, j = n, m
    while i > 0 or j > 0:
        prev_i, prev_j, action = back[i][j]
        if action == "match":
            pairs.append((i - 1, j - 1))
        elif action == "missed":
            pairs.append((i - 1, None))
        else:
            pairs.append((None, j - 1))
        i, j = prev_i, prev_j
    pairs.reverse()
    return pairs


def compare_candidate_event_sequences(
    demo_events: list,
    student_events: list,
    title: str = "Audio Demo Comparison",
    config: Optional[ScoringConfig] = None,
    gap_cost: float = 0.08,
    duplicate_extra_window_sec: float = 0.3,
) -> dict:
    """Compare two extracted event sequences with tempo-invariant DTW."""
    config = config or ScoringConfig()
    pairs = _dtw_align_events(demo_events, student_events, gap_cost=gap_cost)
    matched_time_pairs = [
        (demo_events[i]["onset_sec"], student_events[j]["onset_sec"])
        for i, j in pairs
        if i is not None and j is not None
        and _best_shared_pitch(demo_events[i], student_events[j]) is not None
    ]
    if len(matched_time_pairs) >= 2:
        xs = np.array([p[0] for p in matched_time_pairs], dtype=float)
        ys = np.array([p[1] for p in matched_time_pairs], dtype=float)
        tempo_ratio, intercept = np.polyfit(xs, ys, 1)
        tempo_ratio = float(tempo_ratio)
        intercept = float(intercept)
    else:
        demo_duration = max((e["onset_sec"] for e in demo_events), default=0.0)
        student_duration = max((e["onset_sec"] for e in student_events), default=0.0)
        tempo_ratio = (student_duration / demo_duration) if demo_duration > 0 else 1.0
        intercept = 0.0
    tol_ms = config.effective_tol_ms(120)
    note_results = []
    for demo_idx, student_idx in pairs:
        demo_event = demo_events[demo_idx] if demo_idx is not None else None
        student_event = student_events[student_idx] if student_idx is not None else None
        if demo_event is not None and student_event is not None:
            predicted_student_onset = demo_event["onset_sec"] * tempo_ratio + intercept
            offset_ms = (student_event["onset_sec"] - predicted_student_onset) * 1000.0
            shared_pitch = _best_shared_pitch(demo_event, student_event)
            if shared_pitch is not None:
                status = "correct" if abs(offset_ms) <= tol_ms else "timing_off"
                pitch_ref = shared_pitch
                pitch_perf = shared_pitch
            else:
                status = "wrong_pitch"
                pitch_ref = int(demo_event["pitch"])
                pitch_perf = int(student_event["pitch"])
            timing = "accurate" if abs(offset_ms) <= tol_ms else ("rush" if offset_ms < 0 else "drag")
            note_results.append(NoteResult(
                ref_index=demo_idx,
                perf_index=student_idx,
                pitch_ref=pitch_ref,
                pitch_perf=pitch_perf,
                name=midi_pitch_to_name(pitch_ref),
                onset_ref_sec=float(demo_event["onset_sec"]),
                onset_perf_sec=float(student_event["onset_sec"]),
                offset_ms=offset_ms,
                status=status,
                timing=timing,
                measure=int(demo_event["onset_sec"] // 2.0) + 1,
                hand="R",
                dur_beats=1.0,
            ))
        elif demo_event is not None:
            note_results.append(NoteResult(
                ref_index=demo_idx,
                perf_index=None,
                pitch_ref=int(demo_event["pitch"]),
                pitch_perf=None,
                name=midi_pitch_to_name(int(demo_event["pitch"])),
                onset_ref_sec=float(demo_event["onset_sec"]),
                onset_perf_sec=None,
                offset_ms=None,
                status="missed",
                timing=None,
                measure=int(demo_event["onset_sec"] // 2.0) + 1,
                hand="R",
                dur_beats=1.0,
            ))
        else:
            note_results.append(NoteResult(
                ref_index=None,
                perf_index=student_idx,
                pitch_ref=None,
                pitch_perf=int(student_event["pitch"]),
                name=midi_pitch_to_name(int(student_event["pitch"])),
                onset_ref_sec=None,
                onset_perf_sec=float(student_event["onset_sec"]),
                offset_ms=None,
                status="extra",
                timing=None,
                measure=None,
                hand=None,
            ))

    note_results, duplicate_extras_removed = _suppress_duplicate_extras(
        note_results, student_events, duplicate_extra_window_sec
    )
    summary = _summarize(note_results, config, tempo_ratio)
    return {
        "song_name": title,
        "summary": {
            "score": summary.score,
            "sub_scores": summary.sub_scores,
            "global_tempo_ratio": summary.global_tempo_ratio,
            "tempo_trend": summary.tempo_trend,
            "counts": summary.counts,
            "harmonic_extras_removed": summary.harmonic_extras_removed,
            "octave_slips_in_wrong_pitch": summary.octave_slips_in_wrong_pitch,
        },
        "notes": [
            {
                "ref_index": n.ref_index,
                "perf_index": n.perf_index,
                "pitch_ref": n.pitch_ref,
                "pitch_perf": n.pitch_perf,
                "name": n.name,
                "onset_ref_sec": n.onset_ref_sec,
                "onset_perf_sec": n.onset_perf_sec,
                "offset_ms": n.offset_ms,
                "status": n.status,
                "timing": n.timing,
                "measure": n.measure,
                "hand": n.hand,
                "dur_beats": n.dur_beats,
            }
            for n in note_results
        ],
        "pipeline": {
            "audio_to_performance": "demo_audio_reference_dtw",
            "demo_audio_reference": {
                "demo_events": len(demo_events),
                "student_events": len(student_events),
                "dtw_pairs": len(pairs),
                "duplicate_extras_removed": duplicate_extras_removed,
            },
        },
    }


def _event_pitch_set(event: dict, top_k: int = 5) -> set[int]:
    return {int(c["pitch"]) for c in event.get("candidates", [])[:top_k]} or {int(event["pitch"])}


def _suppress_duplicate_extras(note_results: list, student_events: list, window_sec: float) -> tuple[list, int]:
    matched = [
        result for result in note_results
        if result.status in {"correct", "timing_off"} and result.perf_index is not None
    ]
    kept = []
    removed = 0
    for result in note_results:
        if result.status != "extra" or result.perf_index is None:
            kept.append(result)
            continue
        extra_event = student_events[result.perf_index]
        extra_pitches = _event_pitch_set(extra_event)
        duplicate = False
        for match in matched:
            matched_event = student_events[match.perf_index]
            if abs(extra_event["onset_sec"] - matched_event["onset_sec"]) > window_sec:
                continue
            if extra_pitches & _event_pitch_set(matched_event):
                duplicate = True
                break
        if duplicate:
            removed += 1
        else:
            kept.append(result)
    return kept, removed


def build_audio_reference(
    audio_path: str,
    config: Optional[ReferenceConstrainedConfig] = None,
    title: Optional[str] = None,
    sr: int = 44100,
) -> tuple[dict, dict]:
    """Load a demo recording and build a generated reference from it."""
    audio, sample_rate = librosa.load(audio_path, sr=sr, mono=True)
    events, debug = extract_audio_events(audio, sample_rate, config)
    reference = events_to_reference(events, title=title or audio_path)
    debug = dict(debug)
    debug["audio_path"] = audio_path
    debug["reference_notes"] = len(reference["notes"])
    return reference, debug


def grade_student_against_demo(
    demo_audio_path: str,
    student_audio_path: str,
    config: Optional[ReferenceConstrainedConfig] = None,
    title: Optional[str] = None,
    sr: int = 44100,
) -> tuple[dict, dict]:
    """Build a demo-audio reference and score a student's audio against it."""
    config = config or ReferenceConstrainedConfig()
    demo_audio, sample_rate = librosa.load(demo_audio_path, sr=sr, mono=True)
    demo_events, demo_debug = extract_candidate_events(demo_audio, sample_rate, config)
    student_audio, sample_rate = librosa.load(student_audio_path, sr=sr, mono=True)
    student_events, student_debug = extract_candidate_events(student_audio, sample_rate, config)
    result = compare_candidate_event_sequences(
        demo_events,
        student_events,
        title=title or demo_audio_path,
        config=ScoringConfig(tol_ms=config.audio_compare_tol_ms),
        gap_cost=config.audio_compare_gap_cost,
        duplicate_extra_window_sec=config.duplicate_extra_window_sec,
    )
    result["pipeline"]["demo_audio_reference"]["demo_audio_path"] = demo_audio_path
    result["pipeline"]["demo_audio_reference"]["student_audio_path"] = student_audio_path
    debug = {
        "demo": demo_debug,
        "student": student_debug,
    }
    return result, debug
