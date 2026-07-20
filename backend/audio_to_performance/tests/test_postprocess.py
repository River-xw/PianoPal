"""Unit tests for the harmonic-artifact and note-split post-filters (postprocess.py)."""
from __future__ import annotations

from backend.audio_to_performance.postprocess import suppress_harmonic_artifacts, suppress_note_splits


def _note(pitch, onset_sec, velocity, dur_sec=0.5):
    return {"pitch": pitch, "onset_sec": onset_sec, "dur_sec": dur_sec, "velocity": velocity}


class TestSuppressHarmonicArtifacts:
    def test_quiet_octave_of_a_loud_note_is_suppressed(self):
        notes = [_note(60, 0.0, 90), _note(72, 0.01, 40)]  # C4 loud, C5 (octave) quiet & close
        result = suppress_harmonic_artifacts(notes)
        assert len(result) == 1
        assert result[0]["pitch"] == 60

    def test_quiet_fifth_of_a_loud_note_is_suppressed(self):
        notes = [_note(60, 0.0, 90), _note(67, 0.02, 45)]  # C4 loud, G4 (perfect 5th) quiet
        result = suppress_harmonic_artifacts(notes)
        assert len(result) == 1
        assert result[0]["pitch"] == 60

    def test_quiet_compound_fifth_of_a_loud_note_is_suppressed(self):
        # E3 loud, B4 (octave + perfect fifth = 19 semitones) quiet & close --
        # found on a real transcription as an isolated note floating above
        # the melody with no melodic connection
        notes = [_note(52, 0.0, 90), _note(71, 0.02, 46)]
        result = suppress_harmonic_artifacts(notes)
        assert len(result) == 1
        assert result[0]["pitch"] == 52

    def test_delayed_compound_fifth_needs_the_wider_default_window(self):
        """On a real transcription, this specific artifact consistently
        appeared ~0.3s *after* its source note, not at the same instant --
        the default window (0.35s) must be wide enough to catch it, and a
        too-narrow window (the original 0.1s) demonstrably misses it.
        """
        notes = [_note(52, 0.0, 90), _note(71, 0.3, 46)]
        assert len(suppress_harmonic_artifacts(notes, window_sec=0.1)) == 2  # too narrow: misses it
        result = suppress_harmonic_artifacts(notes)  # default window
        assert len(result) == 1
        assert result[0]["pitch"] == 52

    def test_two_similarly_loud_octave_notes_both_kept(self):
        """A genuine, intentional octave-doubled chord (common in piano
        writing) should NOT be suppressed just because it's an octave apart
        -- only suppressed when one is clearly quieter than the other.
        """
        notes = [_note(60, 0.0, 90), _note(72, 0.01, 85)]
        result = suppress_harmonic_artifacts(notes)
        assert len(result) == 2

    def test_non_harmonic_interval_not_suppressed(self):
        # a major second apart (interval=2) -- not in the harmonic set, keep both
        notes = [_note(60, 0.0, 90), _note(62, 0.01, 30)]
        result = suppress_harmonic_artifacts(notes)
        assert len(result) == 2

    def test_harmonic_interval_but_too_far_apart_in_time_not_suppressed(self):
        notes = [_note(60, 0.0, 90), _note(72, 5.0, 30)]  # 5 seconds apart
        result = suppress_harmonic_artifacts(notes, window_sec=0.1)
        assert len(result) == 2

    def test_quiet_note_played_alone_is_never_touched(self):
        notes = [_note(60, 0.0, 30)]
        result = suppress_harmonic_artifacts(notes)
        assert len(result) == 1

    def test_output_is_time_sorted(self):
        notes = [_note(60, 0.5, 90), _note(64, 0.0, 80), _note(67, 0.25, 85)]
        result = suppress_harmonic_artifacts(notes)
        onsets = [n["onset_sec"] for n in result]
        assert onsets == sorted(onsets)

    def test_deterministic(self):
        notes = [_note(60, 0.0, 90), _note(72, 0.01, 40), _note(64, 0.3, 70)]
        a = suppress_harmonic_artifacts(notes)
        b = suppress_harmonic_artifacts(notes)
        assert a == b


class TestSuppressNoteSplits:
    def test_quiet_reattack_within_a_held_notes_sustain_is_suppressed(self):
        # a C4 held for 1s, re-detected quieter at 0.5s into its own sustain
        notes = [_note(60, 0.0, 90, dur_sec=1.0), _note(60, 0.5, 55, dur_sec=0.4)]
        result = suppress_note_splits(notes)
        assert len(result) == 1
        assert result[0]["onset_sec"] == 0.0

    def test_reattack_after_the_note_has_ended_is_kept(self):
        # a genuine second strike of the same key, after the first note ended
        notes = [_note(60, 0.0, 90, dur_sec=0.5), _note(60, 0.6, 55, dur_sec=0.5)]
        result = suppress_note_splits(notes)
        assert len(result) == 2

    def test_similarly_loud_repeat_within_sustain_is_kept(self):
        # e.g. a genuine fast repeated-note figure struck at similar volume
        notes = [_note(60, 0.0, 90, dur_sec=1.0), _note(60, 0.5, 85, dur_sec=0.4)]
        result = suppress_note_splits(notes)
        assert len(result) == 2

    def test_different_pitch_within_sustain_is_untouched(self):
        # harmonic-interval case belongs to suppress_harmonic_artifacts, not this
        notes = [_note(60, 0.0, 90, dur_sec=1.0), _note(72, 0.5, 40, dur_sec=0.4)]
        result = suppress_note_splits(notes)
        assert len(result) == 2

    def test_output_is_time_sorted(self):
        notes = [_note(60, 0.5, 90), _note(64, 0.0, 80), _note(67, 0.25, 85)]
        result = suppress_note_splits(notes)
        onsets = [n["onset_sec"] for n in result]
        assert onsets == sorted(onsets)

    def test_deterministic(self):
        notes = [_note(60, 0.0, 90, dur_sec=1.0), _note(60, 0.5, 55, dur_sec=0.4)]
        a = suppress_note_splits(notes)
        b = suppress_note_splits(notes)
        assert a == b


class TestFilterImpossiblePitches:
    """The 37-key physical constraint (backend/hardware.py): out-of-range
    transcriptions from a recording of the keyboard are guaranteed artifacts.
    """

    def test_out_of_range_notes_dropped_in_range_kept(self):
        from backend.audio_to_performance.postprocess import filter_impossible_pitches
        notes = [
            _note(36, 0.0, 80),   # below 48 -- impossible
            _note(48, 0.0, 80),   # lowest key -- kept
            _note(60, 1.0, 80),   # kept
            _note(84, 2.0, 80),   # highest key -- kept
            _note(96, 2.0, 40),   # above 84 -- impossible (octave-up ghost)
        ]
        kept = filter_impossible_pitches(notes, (48, 84))
        assert [n["pitch"] for n in kept] == [48, 60, 84]

    def test_empty_list_ok(self):
        from backend.audio_to_performance.postprocess import filter_impossible_pitches
        assert filter_impossible_pitches([], (48, 84)) == []
