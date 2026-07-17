"""Tests for the windowed/piecewise tempo curve (align.fit_tempo_curve),
which replaced a single global straight-line tempo fit specifically to
absorb genuine local tempo changes (rubato, a sustained mid-piece speed-up)
instead of letting residual against one global line accumulate and cascade
into misclassified notes -- exactly the failure mode found when testing
against a real recording (see project notes): a performance that was
internally steady in two different sections, at two different paces, scored
badly across the board under the old single-line fit.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.scoring.align import fit_tempo_curve, prepare_sequence
from backend.scoring.config import ScoringConfig
from backend.scoring.score import score_performance

BPM = 120.0
BEAT_SEC = 60.0 / BPM
NUM_NOTES = 160
SPLIT = 80  # notes [0, SPLIT) at ratio 1.0, notes [SPLIT, NUM_NOTES) at ratio 1.3
SLOWDOWN_RATIO = 1.3
PITCH_CYCLE = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79]  # C major-ish, 12 distinct pitches


def _build_reference(num_notes: int = NUM_NOTES) -> dict:
    notes = []
    for i in range(num_notes):
        onset_beats = float(i)
        pitch = PITCH_CYCLE[i % len(PITCH_CYCLE)]
        notes.append({
            "pitch": pitch, "name": f"n{i}",
            "onset_beats": onset_beats, "onset_sec": onset_beats * BEAT_SEC,
            "dur_beats": 1.0, "dur_sec": BEAT_SEC,
            "velocity": 80, "hand": "R", "measure": i // 4 + 1,
        })
    return {
        "title": "Tempo-step test", "tempo_bpm": int(BPM),
        "tempo_map": [{"beat": 0.0, "bpm": BPM}],
        "time_signature": "4/4", "key": "C major",
        "duration_beats": float(num_notes), "duration_sec": num_notes * BEAT_SEC,
        "notes": notes,
    }


def _build_stepped_tempo_performance(reference: dict) -> list:
    """First SPLIT notes played at the reference's own tempo; the rest played
    at a sustained SLOWDOWN_RATIO -- a real, permanent tempo change partway
    through, not a temporary blip.
    """
    performance = []
    split_ref_time = reference["notes"][SPLIT]["onset_sec"] if SPLIT < len(reference["notes"]) else None
    for n in reference["notes"]:
        if n["onset_beats"] < SPLIT:
            onset_sec = n["onset_sec"]
        else:
            onset_sec = split_ref_time + (n["onset_sec"] - split_ref_time) * SLOWDOWN_RATIO
        performance.append({
            "pitch": n["pitch"], "onset_sec": onset_sec, "dur_sec": n["dur_sec"], "velocity": n["velocity"],
        })
    return performance


class TestTempoCurveAbsorbsStepChange:
    def test_score_performance_handles_sustained_mid_piece_slowdown(self):
        reference = _build_reference()
        performance = _build_stepped_tempo_performance(reference)

        result = score_performance(reference, performance, ScoringConfig())

        # both halves were internally perfectly steady -- a curve that tracks
        # local tempo should score this well overall. It won't be ~perfect:
        # windows straddling the (artificially abrupt) step average across
        # both regimes, so a transition band roughly one window wide is
        # expected to show up as timing_off -- real rubato is gradual, not a
        # mathematical discontinuity, so this is a harsher test than reality.
        counts = result.summary.counts
        total = sum(counts.values())
        assert counts["correct"] / total > 0.7, counts
        assert counts["missed"] == 0
        assert counts["extra"] == 0

    def test_timing_off_notes_cluster_at_the_transition_not_scattered(self):
        """The failures a windowed fit does produce should be localized to
        the boundary between regimes, not spread evenly across the whole
        piece -- confirms the mechanism (window-averaging blur at a hard
        transition) rather than a general accuracy problem.
        """
        reference = _build_reference()
        performance = _build_stepped_tempo_performance(reference)
        result = score_performance(reference, performance, ScoringConfig())

        timing_off = [n for n in result.notes if n.status == "timing_off"]
        assert len(timing_off) > 0
        assert all(abs(n.ref_index - SPLIT) < ScoringConfig().tempo_window_notes for n in timing_off)

    def test_local_predictions_track_each_regime(self):
        """Directly check the fitted curve, not just the downstream score:
        predictions early in the piece should reflect ~1.0x pacing, and
        predictions late in the piece should reflect ~1.3x pacing.
        """
        reference = _build_reference()
        performance = _build_stepped_tempo_performance(reference)

        ref_onsets_raw = [n["onset_sec"] for n in reference["notes"]]
        ref_pitches_raw = [n["pitch"] for n in reference["notes"]]
        perf_onsets_raw = [n["onset_sec"] for n in performance]
        perf_pitches_raw = [n["pitch"] for n in performance]

        config = ScoringConfig()
        ref_onsets, ref_pitches, _ = prepare_sequence(ref_onsets_raw, ref_pitches_raw, config.chord_window_sec)
        perf_onsets, perf_pitches, _ = prepare_sequence(perf_onsets_raw, perf_pitches_raw, config.chord_window_sec)

        curve = fit_tempo_curve(ref_onsets, ref_pitches, perf_onsets, perf_pitches, config)

        # local slope near the start: predict() at two nearby early ref times
        early_a, early_b = 2.0, 12.0
        early_slope = (curve.predict(early_b) - curve.predict(early_a)) / (early_b - early_a)
        # local slope near the end
        late_a, late_b = (SPLIT + 20) * BEAT_SEC, (SPLIT + 60) * BEAT_SEC
        late_slope = (curve.predict(late_b) - curve.predict(late_a)) / (late_b - late_a)

        assert early_slope == pytest.approx(1.0, abs=0.05)
        assert late_slope == pytest.approx(SLOWDOWN_RATIO, abs=0.05)

    def test_single_global_line_would_have_failed_this_case(self):
        """Sanity check on the test design itself: confirm a single robust
        fit over the *whole* stepped performance lands on a compromise slope
        that matches neither regime well -- this is what the windowed curve
        is specifically fixing.
        """
        reference = _build_reference()
        performance = _build_stepped_tempo_performance(reference)

        ref_onsets_raw = [n["onset_sec"] for n in reference["notes"]]
        ref_pitches_raw = [n["pitch"] for n in reference["notes"]]
        perf_onsets_raw = [n["onset_sec"] for n in performance]
        perf_pitches_raw = [n["pitch"] for n in performance]

        config = ScoringConfig()
        ref_onsets, ref_pitches, _ = prepare_sequence(ref_onsets_raw, ref_pitches_raw, config.chord_window_sec)
        perf_onsets, perf_pitches, _ = prepare_sequence(perf_onsets_raw, perf_pitches_raw, config.chord_window_sec)

        curve = fit_tempo_curve(ref_onsets, ref_pitches, perf_onsets, perf_pitches, config)
        # the single robust slope over the whole piece is a compromise between 1.0 and 1.3
        assert 1.0 < curve.representative_slope < SLOWDOWN_RATIO
