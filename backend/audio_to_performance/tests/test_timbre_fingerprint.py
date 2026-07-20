"""Tests for timbre_fingerprint.py -- synthetic (hand-built notes/onsets),
no real audio needed for the alignment/grouping logic; save/load round-trips
through a real tmp file.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.audio_to_performance.constrained_verification import ConstrainedVerificationConfig
from backend.audio_to_performance.timbre_fingerprint import (
    LabeledSegment,
    _align_events_to_onsets,
    _group_into_single_note_events,
    build_templates,
    load_templates,
    save_templates,
)


def _note(pitch, onset_sec):
    return {"pitch": pitch, "onset_sec": onset_sec}


class TestGroupIntoSingleNoteEvents:
    def test_a_chord_is_excluded_a_single_note_is_kept(self):
        notes = [
            _note(60, 0.0), _note(64, 0.01), _note(67, 0.02),  # chord, all within window
            _note(72, 1.0),  # a lone note far from anything else
        ]
        events = _group_into_single_note_events(notes, window_sec=0.06)
        assert len(events) == 1
        assert events[0][0]["pitch"] == 72

    def test_all_single_notes_kept_when_well_separated(self):
        notes = [_note(60, 0.0), _note(62, 0.6), _note(64, 1.2)]
        events = _group_into_single_note_events(notes, window_sec=0.06)
        assert len(events) == 3


class TestAlignEventsToOnsets:
    def test_sequential_nearest_match_in_order(self):
        events = [[_note(60, 0.0)], [_note(62, 1.0)], [_note(64, 2.0)]]
        onset_times = np.array([0.05, 1.02, 2.10])
        aligned = _align_events_to_onsets(events, onset_times, tol_sec=1.5)
        assert aligned == [(60, 0.05), (62, 1.02), (64, 2.10)]

    def test_event_with_no_close_onset_is_dropped(self):
        events = [[_note(60, 0.0)], [_note(62, 100.0)]]  # 100s: nothing that far away
        onset_times = np.array([0.02])
        aligned = _align_events_to_onsets(events, onset_times, tol_sec=1.5)
        assert aligned == [(60, 0.02)]

    def test_each_onset_used_at_most_once(self):
        events = [[_note(60, 0.0)], [_note(62, 0.1)]]
        onset_times = np.array([0.05])  # only one real onset for two events
        aligned = _align_events_to_onsets(events, onset_times, tol_sec=1.5)
        assert len(aligned) == 1


def _frame(vec):
    from backend.audio_to_performance.constrained_verification import CQTFrame
    return CQTFrame(magnitudes=np.array(vec, dtype=float), fmin_hz=27.5, bins_per_octave=36)


class TestBuildTemplates:
    def test_single_occurrence_pitch_gets_a_normalized_template(self):
        segments = [LabeledSegment(pitch=60, onset_sec=0.0, cqt_frame=_frame([3.0, 4.0, 0.0]))]
        templates = build_templates(segments)
        assert 60 in templates
        assert templates[60] == pytest.approx([0.6, 0.8, 0.0])

    def test_multiple_occurrences_are_averaged(self):
        segments = [
            LabeledSegment(pitch=60, onset_sec=0.0, cqt_frame=_frame([1.0, 0.0])),
            LabeledSegment(pitch=60, onset_sec=1.0, cqt_frame=_frame([0.0, 1.0])),
        ]
        templates = build_templates(segments)
        # average of [1,0] and [0,1] normalized -> [0.5, 0.5] normalized -> [0.707, 0.707]
        assert templates[60] == pytest.approx([0.7071, 0.7071], abs=1e-3)

    def test_different_pitches_get_independent_templates(self):
        segments = [
            LabeledSegment(pitch=60, onset_sec=0.0, cqt_frame=_frame([1.0, 0.0])),
            LabeledSegment(pitch=64, onset_sec=1.0, cqt_frame=_frame([0.0, 1.0])),
        ]
        templates = build_templates(segments)
        assert set(templates.keys()) == {60, 64}


class TestSaveLoadRoundTrip:
    def test_round_trips_exactly(self, tmp_path):
        segments = [LabeledSegment(pitch=60, onset_sec=0.0, cqt_frame=_frame([3.0, 4.0]))]
        templates = build_templates(segments)
        path = str(tmp_path / "templates.json")
        save_templates(templates, path, instrument_id="test_instrument")

        loaded = load_templates(path)
        assert set(loaded.keys()) == {60}
        assert loaded[60] == pytest.approx(templates[60])

    def test_mismatched_cqt_layout_raises(self, tmp_path):
        import json

        path = str(tmp_path / "bad_templates.json")
        with open(path, "w") as fh:
            json.dump({
                "instrument_id": "x", "cqt_fmin_hz": 999.0,  # wrong on purpose
                "cqt_bins_per_octave": 36, "cqt_n_octaves": 8,
                "templates": {"60": [1.0, 0.0]},
            }, fh)
        with pytest.raises(ValueError, match="cqt_fmin_hz"):
            load_templates(path)
