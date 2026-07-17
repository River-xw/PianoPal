"""Unit tests for compare.py -- hand-constructed note lists, no real
synthesis/transcription involved. Covers every classification the
round-trip tool is meant to distinguish.
"""
from __future__ import annotations

from backend.validation.compare import classify_interval, match_notes


def _note(pitch, onset_sec, name=None):
    return {"pitch": pitch, "onset_sec": onset_sec, "name": name or f"p{pitch}"}


class TestClassifyInterval:
    def test_exact_match(self):
        status, direction, octaves = classify_interval(60, 60)
        assert status == "exact_match" and direction is None and octaves is None

    def test_octave_up(self):
        status, direction, octaves = classify_interval(60, 72)
        assert status == "octave_error" and direction == "up" and octaves == 1

    def test_octave_down(self):
        status, direction, octaves = classify_interval(72, 60)
        assert status == "octave_error" and direction == "down" and octaves == 1

    def test_double_octave_up(self):
        status, direction, octaves = classify_interval(60, 84)
        assert status == "octave_error" and direction == "up" and octaves == 2

    def test_wrong_pitch_not_a_multiple_of_12(self):
        status, direction, octaves = classify_interval(60, 64)  # major third
        assert status == "wrong_pitch" and direction is None and octaves is None

    def test_wrong_pitch_negative_not_a_multiple_of_12(self):
        status, direction, octaves = classify_interval(60, 55)  # -5 semitones
        assert status == "wrong_pitch"


class TestMatchNotes:
    def test_exact_match_case(self):
        ref = [_note(60, 0.0, "C4")]
        transcribed = [_note(60, 0.01)]
        diffs = match_notes(ref, transcribed)
        assert len(diffs) == 1
        assert diffs[0].status == "exact_match"
        assert diffs[0].transcribed_pitch == 60

    def test_octave_error_case(self):
        ref = [_note(60, 0.0, "C4")]
        transcribed = [_note(72, 0.01)]
        diffs = match_notes(ref, transcribed)
        assert len(diffs) == 1
        assert diffs[0].status == "octave_error"
        assert diffs[0].octave_direction == "up"
        assert diffs[0].octave_count == 1

    def test_double_octave_error_case(self):
        ref = [_note(48, 0.0, "C3")]
        transcribed = [_note(72, 0.01)]
        diffs = match_notes(ref, transcribed)
        assert diffs[0].status == "octave_error"
        assert diffs[0].octave_count == 2

    def test_wrong_pitch_case(self):
        ref = [_note(60, 0.0, "C4")]
        transcribed = [_note(64, 0.01)]
        diffs = match_notes(ref, transcribed)
        assert diffs[0].status == "wrong_pitch"

    def test_missed_case(self):
        ref = [_note(60, 0.0, "C4"), _note(64, 1.0, "E4")]
        transcribed = [_note(60, 0.01)]
        diffs = match_notes(ref, transcribed)
        statuses = {d.ref_pitch: d.status for d in diffs if d.ref_pitch is not None}
        assert statuses[64] == "missed"

    def test_extra_case(self):
        ref = [_note(60, 0.0, "C4")]
        transcribed = [_note(60, 0.01), _note(67, 5.0)]
        diffs = match_notes(ref, transcribed)
        extra = [d for d in diffs if d.status == "extra"]
        assert len(extra) == 1
        assert extra[0].transcribed_pitch == 67

    def test_onset_beyond_tolerance_is_missed_not_matched(self):
        ref = [_note(60, 0.0, "C4")]
        transcribed = [_note(60, 1.0)]  # 1 second away, way beyond tolerance
        diffs = match_notes(ref, transcribed, onset_tol_sec=0.1)
        assert diffs[0].status == "missed"

    def test_mixed_bag_all_categories_at_once(self):
        ref = [_note(60, 0.0, "C4"), _note(64, 1.0, "E4"), _note(67, 2.0, "G4"), _note(48, 3.0, "C3")]
        transcribed = [
            _note(60, 0.01),   # exact match for C4
            _note(76, 1.01),   # octave error (up) for E4
            # G4 (ref, onset=2.0) -- no match, becomes "missed"
            _note(72, 3.01),   # double octave error for C3
            _note(90, 10.0),   # extra, no nearby reference note
        ]
        diffs = match_notes(ref, transcribed)
        by_pitch = {d.ref_pitch: d.status for d in diffs if d.ref_pitch is not None}
        assert by_pitch[60] == "exact_match"
        assert by_pitch[64] == "octave_error"
        assert by_pitch[67] == "missed"
        assert by_pitch[48] == "octave_error"
        extra = [d for d in diffs if d.status == "extra"]
        assert len(extra) == 1 and extra[0].transcribed_pitch == 90

    def test_deterministic(self):
        ref = [_note(60, 0.0), _note(64, 1.0)]
        transcribed = [_note(60, 0.01), _note(76, 1.01)]
        a = match_notes(ref, transcribed)
        b = match_notes(ref, transcribed)
        assert [d.status for d in a] == [d.status for d in b]
