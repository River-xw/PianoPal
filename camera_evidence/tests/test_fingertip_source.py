"""Tests for fingertip_source.py's SyntheticFingertipSource."""
from __future__ import annotations

import pytest

from camera_evidence.calibration import calibrate, pixel_to_pitch
from camera_evidence.fingertip_source import MediaPipeFingertipSource, SyntheticFingertipSource

TOP_LEFT, TOP_RIGHT = (0.0, 0.0), (1200.0, 0.0)
BOTTOM_LEFT, BOTTOM_RIGHT = (0.0, 300.0), (1200.0, 300.0)


def _calibration():
    return calibrate(TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT, lowest_pitch=60, highest_pitch=72)


def _reference():
    return {
        "notes": [
            {"pitch": 60, "onset_sec": 0.0},
            {"pitch": 64, "onset_sec": 0.5},
            {"pitch": 67, "onset_sec": 1.0},
            {"pitch": 61, "onset_sec": 1.5},  # a black key, for good measure
            {"pitch": 72, "onset_sec": 2.0},
        ]
    }


class TestSyntheticFingertipSourceNoError:
    def test_always_lands_on_correct_key_when_error_rate_zero(self):
        calibration = _calibration()
        reference = _reference()
        source = SyntheticFingertipSource(reference, calibration, noise_px=0.0, error_rate=0.0)

        for note in reference["notes"]:
            position = source.get_position(note["onset_sec"])
            assert position is not None
            assert pixel_to_pitch(*position, calibration) == note["pitch"]

    def test_no_reading_far_from_any_onset(self):
        calibration = _calibration()
        source = SyntheticFingertipSource(_reference(), calibration, noise_px=0.0, error_rate=0.0)
        assert source.get_position(100.0) is None


class TestMediaPipeStub:
    def test_raises_not_implemented_on_construction(self):
        with pytest.raises(NotImplementedError):
            MediaPipeFingertipSource()
