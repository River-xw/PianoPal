"""Tests for song_range.py -- pure math on a hand-built reference, no audio needed."""
from __future__ import annotations

import pytest

from backend.audio_to_performance.song_range import compute_song_frequency_range


def _reference(pitches):
    return {"notes": [{"pitch": p} for p in pitches]}


def _midi_to_hz(pitch):
    return 440.0 * 2 ** ((pitch - 69) / 12)


class TestComputeSongFrequencyRange:
    def test_spans_the_songs_actual_pitches_plus_padding(self):
        reference = _reference([60, 64, 67])  # C4-E4-G4
        min_hz, max_hz = compute_song_frequency_range(reference, pad_semitones=6)
        assert min_hz == pytest.approx(_midi_to_hz(60 - 6))
        assert max_hz == pytest.approx(_midi_to_hz(67 + 6))

    def test_default_padding_is_6_semitones(self):
        reference = _reference([60])
        min_hz, max_hz = compute_song_frequency_range(reference)
        assert min_hz == pytest.approx(_midi_to_hz(54))
        assert max_hz == pytest.approx(_midi_to_hz(66))

    def test_zero_padding_matches_exact_range(self):
        reference = _reference([48, 72])
        min_hz, max_hz = compute_song_frequency_range(reference, pad_semitones=0)
        assert min_hz == pytest.approx(_midi_to_hz(48))
        assert max_hz == pytest.approx(_midi_to_hz(72))

    def test_single_pitch_song_still_produces_a_range(self):
        reference = _reference([60, 60, 60])  # repeated, same pitch every time
        min_hz, max_hz = compute_song_frequency_range(reference, pad_semitones=3)
        assert min_hz < max_hz
        assert min_hz == pytest.approx(_midi_to_hz(57))
        assert max_hz == pytest.approx(_midi_to_hz(63))

    def test_empty_reference_raises(self):
        with pytest.raises(ValueError):
            compute_song_frequency_range(_reference([]))
