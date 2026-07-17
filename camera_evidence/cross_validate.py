"""Cross-validates scoring/'s result.json against an independent camera-based
fingertip-position evidence source, to resolve octave errors that basic-pitch
can't disambiguate from audio alone (harmonics at 2x/3x/4x the fundamental
frequency look identical in audio; physical key position never does -- C4
and C5 are non-overlapping pixel regions on the keyboard).

Camera only answers "which key was the fingertip over at this timestamp" --
it never confirms a key was actually pressed (that stays with audio/IMU), so
this can relabel a *disputed* note's status but never fabricates a new note
out of camera evidence alone.
"""
from __future__ import annotations

import copy
from typing import Optional

from .calibration import pixel_to_pitch
from .config import CameraEvidenceConfig
from .fingertip_source import FingertipSource

try:
    from backend.validation.compare import classify_interval
except ImportError:  # backend/ not on the path -- reimplement the check
    def classify_interval(ref_pitch: int, other_pitch: int) -> tuple:
        interval = other_pitch - ref_pitch
        if interval == 0:
            return "exact_match", None, None
        if interval % 12 == 0:
            return "octave_error", ("up" if interval > 0 else "down"), abs(interval) // 12
        return "wrong_pitch", None, None


def _query(fingertip_source: FingertipSource, calibration: dict, timestamp_sec: Optional[float]) -> tuple:
    if timestamp_sec is None:
        return None, None
    position = fingertip_source.get_position(timestamp_sec)
    if position is None:
        return None, None
    return position, pixel_to_pitch(position[0], position[1], calibration)


def _resolve_wrong_pitch(note: dict, fingertip_source: FingertipSource, calibration: dict) -> None:
    timestamp = note.get("onset_perf_sec")
    position, camera_pitch = _query(fingertip_source, calibration, timestamp)
    pitch_ref, pitch_perf = note["pitch_ref"], note["pitch_perf"]
    interval_status, _, _ = classify_interval(pitch_ref, pitch_perf)

    evidence = {
        "queried": True,
        "query_timestamp_sec": timestamp,
        "camera_position_px": list(position) if position else None,
        "camera_pitch": camera_pitch,
        "original_status": note["status"],
        "original_pitch_perf": pitch_perf,
        "is_octave_interval": interval_status == "octave_error",
    }

    if camera_pitch is not None and camera_pitch == pitch_ref:
        # camera agrees with the score, not with what basic-pitch heard --
        # this is exactly the harmonic-confusion signature audio alone can't resolve.
        note["status"] = "camera_corrected_octave_error"
        note["pitch_perf"] = pitch_ref
        evidence["flag"] = "camera_corrected_octave_error"
    elif camera_pitch is not None and camera_pitch == pitch_perf:
        # camera agrees with audio -- genuinely a different note, not an artifact.
        evidence["flag"] = "camera_confirms_wrong_pitch"
    else:
        # camera disagrees with both, or gave no reading -- don't guess.
        evidence["flag"] = "camera_evidence_inconclusive"

    note["camera_evidence"] = evidence


def _resolve_missed(note: dict, fingertip_source: FingertipSource, calibration: dict) -> None:
    timestamp = note.get("onset_ref_sec")
    position, camera_pitch = _query(fingertip_source, calibration, timestamp)
    pitch_ref = note["pitch_ref"]

    evidence = {
        "queried": True,
        "query_timestamp_sec": timestamp,
        "camera_position_px": list(position) if position else None,
        "camera_pitch": camera_pitch,
        "original_status": note["status"],
        "original_pitch_perf": None,
        "is_octave_interval": None,
    }
    if camera_pitch is not None and camera_pitch == pitch_ref:
        evidence["flag"] = "camera_suggests_missed_detection"
    else:
        evidence["flag"] = "camera_evidence_inconclusive"

    # informational only: camera confirms a finger was over the right key at
    # the right time, but never confirms a key press -- status stays
    # "missed" either way, and no note is fabricated that audio never heard.
    note["camera_evidence"] = evidence


def apply_camera_evidence(
    result: dict,
    fingertip_source: FingertipSource,
    calibration: dict,
    config: Optional[CameraEvidenceConfig] = None,
) -> dict:
    """Returns a new (deep-copied) result dict augmented with a nullable
    per-note `camera_evidence` field, and an updated `summary.counts` /
    `summary.camera_evidence_summary`. The input result is never mutated.
    """
    config = config or CameraEvidenceConfig()
    augmented = copy.deepcopy(result)

    for note in augmented["notes"]:
        note.setdefault("camera_evidence", None)
        status = note["status"]
        if status not in config.trigger_statuses:
            continue
        if status == "wrong_pitch":
            _resolve_wrong_pitch(note, fingertip_source, calibration)
        elif status == "missed":
            _resolve_missed(note, fingertip_source, calibration)

    augmented["summary"] = _update_summary(augmented["summary"], augmented["notes"])
    return augmented


_FLAG_TO_SUMMARY_KEY = {
    "camera_corrected_octave_error": "octave_errors_resolved",
    "camera_confirms_wrong_pitch": "wrong_pitch_confirmed",
    "camera_suggests_missed_detection": "missed_with_camera_support",
    "camera_evidence_inconclusive": "inconclusive",
}


def _update_summary(summary: dict, notes: list) -> dict:
    summary = copy.deepcopy(summary)

    counts: dict = {}
    for note in notes:
        counts[note["status"]] = counts.get(note["status"], 0) + 1
    summary["counts"] = counts

    camera_summary = {key: 0 for key in _FLAG_TO_SUMMARY_KEY.values()}
    for note in notes:
        evidence = note.get("camera_evidence")
        if not evidence:
            continue
        key = _FLAG_TO_SUMMARY_KEY.get(evidence["flag"])
        if key:
            camera_summary[key] += 1
    summary["camera_evidence_summary"] = camera_summary

    return summary
