"""Tests for constrained_verification.py -- all synthetic (hand-built CQT
energy arrays / onset lists), no real audio needed.
"""
from __future__ import annotations

import numpy as np

from audio_to_performance.constrained_verification import (
    CQTFrame,
    ConstrainedVerificationConfig,
    _flag_unexpected_onsets,
    get_candidates,
    reverify_note,
    score_candidate,
)

FMIN = 27.5   # A0
BPO = 36      # bins per octave
N_BINS = BPO * 8


def _midi_to_bin(pitch: int, fmin=FMIN, bins_per_octave=BPO) -> int:
    freq = 440.0 * (2.0 ** ((pitch - 69) / 12.0))
    return int(round(bins_per_octave * np.log2(freq / fmin)))


def _frame_with_energy(energy_by_pitch: dict) -> CQTFrame:
    magnitudes = np.zeros(N_BINS)
    for pitch, energy in energy_by_pitch.items():
        magnitudes[_midi_to_bin(pitch)] = energy
    return CQTFrame(magnitudes=magnitudes, fmin_hz=FMIN, bins_per_octave=BPO)


class TestGetCandidates:
    def test_no_range_returns_all_offsets(self):
        candidates = get_candidates(60, keyboard_range=None)
        assert set(candidates) == {36, 48, 58, 59, 60, 61, 62, 72, 84}

    def test_narrow_range_filters_out_of_range_octave(self):
        # ref_pitch near the TOP of a narrow range -- +12/+24 should be filtered out
        candidates = get_candidates(80, keyboard_range=(21, 84))
        assert 92 not in candidates  # would be +12, out of range
        assert 104 not in candidates  # would be +24, out of range
        assert 80 in candidates
        assert 68 in candidates  # -12, in range

    def test_deduplicates(self):
        candidates = get_candidates(60)
        assert len(candidates) == len(set(candidates))


class TestScoreCandidateHarmonicDiscount:
    def test_octave_up_of_strong_lower_candidate_is_discounted(self):
        config = ConstrainedVerificationConfig()
        ref_pitch = 48
        candidates = get_candidates(ref_pitch)  # includes 48 and 60 (+12)
        # ref (48) strong, its octave-up (60) present but weak (< 0.4x) -- a harmonic, not a real note
        frame = _frame_with_energy({48: 1.0, 60: 0.3})

        score_ref = score_candidate(frame, 48, ref_pitch, candidates, config)
        score_octave = score_candidate(frame, 60, ref_pitch, candidates, config)

        assert score_ref > score_octave
        # confirm the discount actually fired (raw energy at 60 was 0.3, discounted score much lower)
        assert score_octave < 0.3

    def test_genuine_independent_pitch_is_not_suppressed(self):
        config = ConstrainedVerificationConfig()
        ref_pitch = 48
        candidates = get_candidates(ref_pitch)  # includes 48 and 49 (+1), not a multiple of 12 from ref
        # a genuinely different, independently strong note with no strong lower-octave explanation
        frame = _frame_with_energy({48: 0.2, 49: 1.0})

        score_ref = score_candidate(frame, 48, ref_pitch, candidates, config)
        score_other = score_candidate(frame, 49, ref_pitch, candidates, config)

        assert score_other > score_ref  # genuine wrong note wins, not suppressed


class TestReverifyNoteOutcomes:
    def _note(self, pitch_ref=60, pitch_perf=72, status="wrong_pitch"):
        return {
            "ref_index": 0, "perf_index": 0, "pitch_ref": pitch_ref, "pitch_perf": pitch_perf,
            "name": "note", "onset_ref_sec": 1.0, "onset_perf_sec": 1.0, "offset_ms": 0.0,
            "status": status, "timing": "accurate", "measure": 1, "hand": "right", "dur_beats": 1.0,
        }

    def test_octave_confusion_corrected(self):
        # ref (60) strong, its octave-up (72, the original wrong basic-pitch guess) weak -- a harmonic
        frame = _frame_with_energy({60: 1.0, 72: 0.2})
        note = self._note(pitch_ref=60, pitch_perf=72, status="wrong_pitch")

        result = reverify_note(note, audio_window=None, sr=None, cqt_frame=frame)

        assert result["status"] == "corrected_octave_or_harmonic_error"
        assert result["pitch_perf"] == 60
        assert result["verification"]["flag"] == "corrected_octave_or_harmonic_error"
        assert result["verification"]["original_pitch_guess"] == 72

    def test_genuine_wrong_pitch_confirmed(self):
        # ref (60) weak, the actually-performed pitch (62, a near-miss candidate,
        # not a multiple of 12 from ref) strong
        frame = _frame_with_energy({60: 0.1, 62: 1.0})
        note = self._note(pitch_ref=60, pitch_perf=62, status="wrong_pitch")

        result = reverify_note(note, audio_window=None, sr=None, cqt_frame=frame)

        assert result["status"] == "wrong_pitch"  # unchanged -- confirmed genuine
        assert result["pitch_perf"] == 62
        assert result["verification"]["flag"] == "confirmed_genuine"

    def test_inconclusive_when_no_candidate_is_confident(self):
        # near-silence: every candidate has ~equal, negligible energy
        frame = CQTFrame(magnitudes=np.full(N_BINS, 1e-6), fmin_hz=FMIN, bins_per_octave=BPO)
        note = self._note(pitch_ref=60, pitch_perf=72, status="wrong_pitch")

        result = reverify_note(note, audio_window=None, sr=None, cqt_frame=frame)

        assert result["status"] == "wrong_pitch"  # untouched
        assert result["pitch_perf"] == 72          # untouched
        assert result["verification"]["flag"] == "reverification_inconclusive"

    def test_reverified_to_a_third_pitch(self):
        # neither ref (60) nor the original guess (72) wins -- a third candidate does
        frame = _frame_with_energy({60: 0.1, 72: 0.1, 61: 1.0})
        note = self._note(pitch_ref=60, pitch_perf=72, status="wrong_pitch")

        result = reverify_note(note, audio_window=None, sr=None, cqt_frame=frame)

        assert result["status"] == "reverified_different_pitch"
        assert result["pitch_perf"] == 61
        assert result["verification"]["flag"] == "reverified_different_pitch"

    def test_missed_note_can_be_corrected_too(self):
        note = self._note(pitch_ref=64, pitch_perf=None, status="missed")
        note["onset_perf_sec"] = None
        frame = _frame_with_energy({64: 1.0})

        result = reverify_note(note, audio_window=None, sr=None, cqt_frame=frame)

        assert result["status"] == "corrected_octave_or_harmonic_error"
        assert result["pitch_perf"] == 64


class TestReverifyNoteNeverSilentlyOverwrites:
    def test_inconclusive_never_changes_status_regression(self):
        for pitch_ref, pitch_perf, status in [(60, 72, "wrong_pitch"), (67, None, "missed")]:
            frame = CQTFrame(magnitudes=np.full(N_BINS, 1e-9), fmin_hz=FMIN, bins_per_octave=BPO)
            note = {
                "ref_index": 0, "perf_index": 0 if pitch_perf else None,
                "pitch_ref": pitch_ref, "pitch_perf": pitch_perf,
                "name": "note", "onset_ref_sec": 1.0, "onset_perf_sec": 1.0 if pitch_perf else None,
                "offset_ms": None, "status": status, "timing": None, "measure": 1, "hand": "right",
                "dur_beats": 1.0,
            }
            result = reverify_note(note, audio_window=None, sr=None, cqt_frame=frame)
            assert result["status"] == status
            assert result["pitch_perf"] == pitch_perf
            assert result["verification"]["flag"] == "reverification_inconclusive"


class TestFlagUnexpectedOnsets:
    def test_onset_far_from_reference_is_flagged(self):
        config = ConstrainedVerificationConfig(onset_gap_sec=0.2)
        onset_times = [5.0]
        known_onsets = [0.0, 1.0, 2.0]
        flagged = _flag_unexpected_onsets(onset_times, known_onsets, config)
        assert len(flagged) == 1
        assert flagged[0]["onset_sec"] == 5.0
        assert flagged[0]["flag"] == "possible_unscored_extra_onset"

    def test_onset_near_reference_is_not_flagged(self):
        config = ConstrainedVerificationConfig(onset_gap_sec=0.2)
        onset_times = [1.05]
        known_onsets = [0.0, 1.0, 2.0]
        flagged = _flag_unexpected_onsets(onset_times, known_onsets, config)
        assert flagged == []

    def test_mixed_onsets(self):
        config = ConstrainedVerificationConfig(onset_gap_sec=0.2)
        onset_times = [1.0, 1.05, 5.0, 2.0]
        known_onsets = [0.0, 1.0, 2.0]
        flagged = _flag_unexpected_onsets(onset_times, known_onsets, config)
        assert [f["onset_sec"] for f in flagged] == [5.0]
