"""Tests for calibration.py: the homography-based pixel<->pitch mapping and
the standard white/black key layout it's built on.
"""
from __future__ import annotations

from camera_evidence.calibration import calibrate, pitch_to_pixel, pixel_to_pitch
from camera_evidence.config import CameraEvidenceConfig

# a simple axis-aligned "photo": 1200x300px, one octave, C4 (60) to C5 (72),
# matching the spec's own 37-key example style but scaled down for a quick test
TOP_LEFT = (0.0, 0.0)
TOP_RIGHT = (1200.0, 0.0)
BOTTOM_LEFT = (0.0, 300.0)
BOTTOM_RIGHT = (1200.0, 300.0)


def _calibration(**overrides):
    config = CameraEvidenceConfig(**overrides) if overrides else None
    return calibrate(TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT, lowest_pitch=60, highest_pitch=72, config=config)


class TestCornersMapToRangeEndpoints:
    def test_top_left_is_lowest_pitch(self):
        calibration = _calibration()
        assert pixel_to_pitch(*TOP_LEFT, calibration) == 60

    def test_top_right_is_highest_pitch(self):
        calibration = _calibration()
        assert pixel_to_pitch(*TOP_RIGHT, calibration) == 72

    def test_bottom_left_is_lowest_pitch(self):
        calibration = _calibration()
        assert pixel_to_pitch(*BOTTOM_LEFT, calibration) == 60

    def test_bottom_right_is_highest_pitch(self):
        calibration = _calibration()
        assert pixel_to_pitch(*BOTTOM_RIGHT, calibration) == 72


class TestOutsideRegionReturnsNone:
    def test_far_outside_returns_none(self):
        calibration = _calibration()
        assert pixel_to_pitch(-5000.0, -5000.0, calibration) is None
        assert pixel_to_pitch(50000.0, 50000.0, calibration) is None

    def test_just_past_edge_within_tolerance_still_resolves(self):
        # default tolerance is 15px; 5px past the left edge should still
        # clip into the keyboard region rather than returning None
        calibration = _calibration(calibration_edge_tolerance_px=15.0)
        assert pixel_to_pitch(-5.0, 150.0, calibration) == 60

    def test_well_past_tolerance_returns_none(self):
        calibration = _calibration(calibration_edge_tolerance_px=15.0)
        assert pixel_to_pitch(-100.0, 150.0, calibration) is None


class TestBlackAndWhiteKeysResolveDifferently:
    def test_adjacent_black_and_white_keys_give_different_pitches(self):
        calibration = _calibration()
        # C#4 (61) is a black key between C4 (60) and D4 (62); D4 itself is white
        csharp_pixel = pitch_to_pixel(61, calibration)
        d4_pixel = pitch_to_pixel(62, calibration)
        assert csharp_pixel is not None and d4_pixel is not None
        assert pixel_to_pitch(*csharp_pixel, calibration) == 61
        assert pixel_to_pitch(*d4_pixel, calibration) == 62

    def test_same_horizontal_position_white_only_zone_vs_black_zone(self):
        calibration = _calibration()
        csharp_pixel = pitch_to_pixel(61, calibration)  # near the back (black-key zone)
        assert csharp_pixel is not None
        x, _ = csharp_pixel
        # near the front of the keys (white-only zone), same x, should NOT be black
        front_y = 0.95 * BOTTOM_LEFT[1]
        assert pixel_to_pitch(x, front_y, calibration) != 61

    def test_every_white_key_round_trips(self):
        calibration = _calibration()
        for entry in calibration["white_keys"]:
            pixel = pitch_to_pixel(entry["pitch"], calibration)
            assert pixel is not None
            assert pixel_to_pitch(*pixel, calibration) == entry["pitch"]

    def test_every_black_key_round_trips(self):
        calibration = _calibration()
        for entry in calibration["black_keys"]:
            pixel = pitch_to_pixel(entry["pitch"], calibration)
            assert pixel is not None
            assert pixel_to_pitch(*pixel, calibration) == entry["pitch"]


class TestKeyLayout:
    def test_no_black_key_between_e_and_f_or_b_and_c(self):
        # two-octave range so both E-F and B-C boundaries are present
        calibration = calibrate(TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT, lowest_pitch=60, highest_pitch=84)
        black_pitches = {k["pitch"] for k in calibration["black_keys"]}
        # standard layout: black-key pitch classes are exactly C#,D#,F#,G#,A# --
        # nothing at E#/B# (i.e. no gap between E-F or B-C)
        assert {p % 12 for p in black_pitches} == {1, 3, 6, 8, 10}
