"""Tests for cross_validate.py: the core camera-evidence resolution logic."""
from __future__ import annotations

from camera_evidence.calibration import calibrate, pitch_to_pixel
from camera_evidence.cross_validate import apply_camera_evidence
from camera_evidence.fingertip_source import FingertipSource

TOP_LEFT, TOP_RIGHT = (0.0, 0.0), (1200.0, 0.0)
BOTTOM_LEFT, BOTTOM_RIGHT = (0.0, 300.0), (1200.0, 300.0)


def _calibration():
    # two octaves so we have room for a +12 test and assorted pitches
    return calibrate(TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT, lowest_pitch=48, highest_pitch=84)


class _FixedFingertipSource(FingertipSource):
    """Always reports the same pixel position, regardless of timestamp --
    lets each test control exactly what "camera evidence" says.
    """

    def __init__(self, position):
        self._position = position

    def get_position(self, timestamp_sec: float):
        return self._position


def _empty_summary() -> dict:
    return {
        "score": 0.0, "sub_scores": {}, "global_tempo_ratio": None,
        "tempo_trend": "steady", "counts": {},
    }


def _wrong_pitch_note(pitch_ref: int, pitch_perf: int) -> dict:
    return {
        "ref_index": 0, "perf_index": 0, "pitch_ref": pitch_ref, "pitch_perf": pitch_perf,
        "name": "note", "onset_ref_sec": 1.0, "onset_perf_sec": 1.02, "offset_ms": 20.0,
        "status": "wrong_pitch", "timing": "accurate", "measure": 1, "hand": "right", "dur_beats": 1.0,
    }


def _missed_note(pitch_ref: int) -> dict:
    return {
        "ref_index": 0, "perf_index": None, "pitch_ref": pitch_ref, "pitch_perf": None,
        "name": "note", "onset_ref_sec": 1.0, "onset_perf_sec": None, "offset_ms": None,
        "status": "missed", "timing": None, "measure": 1, "hand": "right", "dur_beats": 1.0,
    }


class TestOctaveErrorCorrection:
    def test_plus_12_resolved_when_camera_agrees_with_ref(self):
        calibration = _calibration()
        note = _wrong_pitch_note(pitch_ref=60, pitch_perf=72)  # +12, octave-suspect
        camera_position = pitch_to_pixel(60, calibration)  # camera sees the REF key
        source = _FixedFingertipSource(camera_position)
        result = {"summary": _empty_summary(), "notes": [note]}

        augmented = apply_camera_evidence(result, source, calibration)
        out_note = augmented["notes"][0]

        assert out_note["status"] == "camera_corrected_octave_error"
        assert out_note["pitch_perf"] == 60
        assert out_note["camera_evidence"]["flag"] == "camera_corrected_octave_error"
        assert out_note["camera_evidence"]["is_octave_interval"] is True
        assert out_note["camera_evidence"]["original_pitch_perf"] == 72
        assert augmented["summary"]["camera_evidence_summary"]["octave_errors_resolved"] == 1
        assert augmented["summary"]["counts"].get("wrong_pitch", 0) == 0


class TestGenuineWrongPitchLeftAlone:
    def test_non_octave_interval_camera_agrees_with_performed_stays_wrong_pitch(self):
        calibration = _calibration()
        note = _wrong_pitch_note(pitch_ref=60, pitch_perf=62)  # +2, not an octave
        camera_position = pitch_to_pixel(62, calibration)  # camera agrees with what was HEARD
        source = _FixedFingertipSource(camera_position)
        result = {"summary": _empty_summary(), "notes": [note]}

        augmented = apply_camera_evidence(result, source, calibration)
        out_note = augmented["notes"][0]

        assert out_note["status"] == "wrong_pitch"
        assert out_note["pitch_perf"] == 62
        assert out_note["camera_evidence"]["flag"] == "camera_confirms_wrong_pitch"
        assert out_note["camera_evidence"]["is_octave_interval"] is False


class TestInconclusive:
    def test_camera_disagrees_with_both_leaves_status_untouched(self):
        calibration = _calibration()
        note = _wrong_pitch_note(pitch_ref=60, pitch_perf=72)
        camera_position = pitch_to_pixel(65, calibration)  # neither ref (60) nor perf (72)
        source = _FixedFingertipSource(camera_position)
        result = {"summary": _empty_summary(), "notes": [note]}

        augmented = apply_camera_evidence(result, source, calibration)
        out_note = augmented["notes"][0]

        assert out_note["status"] == "wrong_pitch"  # untouched, no silent guessing
        assert out_note["pitch_perf"] == 72
        assert out_note["camera_evidence"]["flag"] == "camera_evidence_inconclusive"

    def test_no_camera_reading_at_all_is_inconclusive(self):
        calibration = _calibration()
        note = _wrong_pitch_note(pitch_ref=60, pitch_perf=72)
        source = _FixedFingertipSource(None)  # no reading
        result = {"summary": _empty_summary(), "notes": [note]}

        augmented = apply_camera_evidence(result, source, calibration)
        out_note = augmented["notes"][0]

        assert out_note["status"] == "wrong_pitch"
        assert out_note["camera_evidence"]["flag"] == "camera_evidence_inconclusive"
        assert out_note["camera_evidence"]["camera_pitch"] is None


class TestMissedNotes:
    def test_camera_on_ref_key_flags_but_does_not_add_a_note(self):
        calibration = _calibration()
        note = _missed_note(pitch_ref=64)
        camera_position = pitch_to_pixel(64, calibration)
        source = _FixedFingertipSource(camera_position)
        result = {"summary": _empty_summary(), "notes": [note]}

        augmented = apply_camera_evidence(result, source, calibration)

        assert len(augmented["notes"]) == 1  # no note silently added
        out_note = augmented["notes"][0]
        assert out_note["status"] == "missed"  # status unchanged -- press/no-press isn't camera's call
        assert out_note["camera_evidence"]["flag"] == "camera_suggests_missed_detection"
        assert augmented["summary"]["camera_evidence_summary"]["missed_with_camera_support"] == 1

    def test_camera_elsewhere_leaves_missed_inconclusive(self):
        calibration = _calibration()
        note = _missed_note(pitch_ref=64)
        camera_position = pitch_to_pixel(67, calibration)  # different key
        source = _FixedFingertipSource(camera_position)
        result = {"summary": _empty_summary(), "notes": [note]}

        augmented = apply_camera_evidence(result, source, calibration)
        out_note = augmented["notes"][0]

        assert out_note["status"] == "missed"
        assert out_note["camera_evidence"]["flag"] == "camera_evidence_inconclusive"


class TestUntouchedStatuses:
    def test_correct_and_extra_notes_are_not_queried(self):
        calibration = _calibration()
        correct_note = {**_wrong_pitch_note(60, 60), "status": "correct"}
        extra_note = {
            "ref_index": None, "perf_index": 0, "pitch_ref": None, "pitch_perf": 60,
            "name": "note", "onset_ref_sec": None, "onset_perf_sec": 1.0, "offset_ms": None,
            "status": "extra", "timing": None, "measure": None, "hand": None, "dur_beats": None,
        }
        source = _FixedFingertipSource((999.0, 999.0))
        result = {"summary": _empty_summary(), "notes": [correct_note, extra_note]}

        augmented = apply_camera_evidence(result, source, calibration)

        assert augmented["notes"][0]["camera_evidence"] is None
        assert augmented["notes"][1]["camera_evidence"] is None
