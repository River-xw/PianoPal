"""Matches a reference note list against a transcribed note list by nearest
onset time, then classifies each matched pair -- isolating OCTAVE_ERROR
(pitch differs by an exact multiple of 12 semitones) as its own category,
distinct from generic wrong_pitch, since that's the specific bug this module
exists to hunt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

Status = str  # "exact_match" | "octave_error" | "wrong_pitch" | "missed" | "extra"


@dataclass
class NoteDiff:
    ref_pitch: Optional[int]
    ref_name: Optional[str]
    transcribed_pitch: Optional[int]
    onset_sec: Optional[float]
    status: Status
    octave_direction: Optional[str] = None  # "up" / "down", only for octave_error
    octave_count: Optional[int] = None      # 1 = a single octave, 2 = two octaves, ...


def classify_interval(ref_pitch: int, transcribed_pitch: int) -> tuple:
    """Returns (status, direction, octave_count) for a matched pair."""
    interval = transcribed_pitch - ref_pitch
    if interval == 0:
        return "exact_match", None, None
    if interval % 12 == 0:
        return "octave_error", ("up" if interval > 0 else "down"), abs(interval) // 12
    return "wrong_pitch", None, None


def match_notes(ref_notes: list, transcribed_notes: list, onset_tol_sec: float = 0.1) -> list:
    """Greedy nearest-onset-time matching: for each reference note (processed
    in onset order, for determinism), pick the closest not-yet-used
    transcribed note within `onset_tol_sec`. Leftover unmatched transcribed
    notes become "extra"; reference notes with no candidate become "missed".
    """
    ref_order = sorted(range(len(ref_notes)), key=lambda i: ref_notes[i]["onset_sec"])
    used_transcribed = set()
    diffs: list = []

    for ref_idx in ref_order:
        ref_note = ref_notes[ref_idx]
        best_j, best_dist = None, None
        for j, t_note in enumerate(transcribed_notes):
            if j in used_transcribed:
                continue
            dist = abs(t_note["onset_sec"] - ref_note["onset_sec"])
            if dist > onset_tol_sec:
                continue
            if best_dist is None or dist < best_dist:
                best_j, best_dist = j, dist

        if best_j is None:
            diffs.append(NoteDiff(
                ref_pitch=ref_note["pitch"], ref_name=ref_note.get("name"),
                transcribed_pitch=None, onset_sec=ref_note["onset_sec"], status="missed",
            ))
            continue

        used_transcribed.add(best_j)
        t_note = transcribed_notes[best_j]
        status, direction, octaves = classify_interval(ref_note["pitch"], t_note["pitch"])
        diffs.append(NoteDiff(
            ref_pitch=ref_note["pitch"], ref_name=ref_note.get("name"),
            transcribed_pitch=t_note["pitch"], onset_sec=ref_note["onset_sec"],
            status=status, octave_direction=direction, octave_count=octaves,
        ))

    for j, t_note in enumerate(transcribed_notes):
        if j not in used_transcribed:
            diffs.append(NoteDiff(
                ref_pitch=None, ref_name=None, transcribed_pitch=t_note["pitch"],
                onset_sec=t_note["onset_sec"], status="extra",
            ))

    return diffs
