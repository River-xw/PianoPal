"""Tests for the scoring engine. `reference` is a small hand-built dict (the
same shape score_to_reference.convert() produces); performances are
synthesized by perturbing it in controlled ways.
"""
from __future__ import annotations

import numpy as np
import pytest

from scoring.score import score_performance

NOTE_NAMES = ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5", "F5", "G5"]
PITCHES = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79]
BPM = 120.0
BEAT_SEC = 60.0 / BPM


def _build_reference() -> dict:
    notes = []
    for i, (name, pitch) in enumerate(zip(NOTE_NAMES, PITCHES)):
        onset_beats = float(i)
        notes.append({
            "pitch": pitch, "name": name,
            "onset_beats": onset_beats, "onset_sec": onset_beats * BEAT_SEC,
            "dur_beats": 1.0, "dur_sec": BEAT_SEC,
            "velocity": 80, "hand": "R", "measure": int(onset_beats // 4) + 1,
        })
    return {
        "title": "Test Scale", "tempo_bpm": int(BPM),
        "tempo_map": [{"beat": 0.0, "bpm": BPM}],
        "time_signature": "4/4", "key": "C major",
        "duration_beats": 12.0, "duration_sec": 12.0 * BEAT_SEC,
        "notes": notes,
    }


def _perfect_performance(reference: dict) -> list:
    return [
        {"pitch": n["pitch"], "onset_sec": n["onset_sec"], "dur_sec": n["dur_sec"], "velocity": n["velocity"]}
        for n in reference["notes"]
    ]


class TestPerfectPerformance:
    def test_score_is_100(self):
        reference = _build_reference()
        performance = _perfect_performance(reference)
        result = score_performance(reference, performance)
        assert result.summary.score == pytest.approx(100.0, abs=0.5)
        assert result.summary.counts == {
            "correct": 12, "timing_off": 0, "wrong_pitch": 0, "missed": 0, "extra": 0,
        }


class TestUniformTempoChange:
    def test_absorbed_by_global_fit(self):
        reference = _build_reference()
        performance = _perfect_performance(reference)
        for n in performance:
            n["onset_sec"] *= 0.92
        result = score_performance(reference, performance)
        assert result.summary.global_tempo_ratio == pytest.approx(0.92, abs=0.01)
        assert result.summary.counts["timing_off"] == 0
        assert result.summary.score > 95.0


class TestGaussianJitter:
    def test_score_decreases_as_sigma_grows(self):
        # A single noisy draw isn't reliably monotonic with only 12 notes --
        # average several trials per sigma to see the true underlying trend.
        reference = _build_reference()
        rng = np.random.default_rng(42)
        mean_scores = []
        for sigma_ms in [0, 10, 30, 60, 120]:
            trial_scores = []
            for _ in range(10):
                performance = _perfect_performance(reference)
                for n in performance:
                    n["onset_sec"] += rng.normal(0, sigma_ms / 1000.0)
                result = score_performance(reference, performance)
                trial_scores.append(result.summary.score)
            mean_scores.append(float(np.mean(trial_scores)))
        assert mean_scores == sorted(mean_scores, reverse=True)


class TestLocalRush:
    def test_notes_5_to_8_flagged_rush(self):
        reference = _build_reference()
        performance = _perfect_performance(reference)
        rushed_positions = [4, 5, 6, 7]  # zero-based indices for "notes 5-8"
        for i in rushed_positions:
            performance[i]["onset_sec"] -= 0.080
        result = score_performance(reference, performance)

        rushed_results = [r for r in result.notes if r.ref_index in rushed_positions]
        assert len(rushed_results) == 4
        for r in rushed_results:
            assert r.status == "timing_off"
            assert r.timing == "rush"

        other_results = [
            r for r in result.notes if r.ref_index is not None and r.ref_index not in rushed_positions
        ]
        for r in other_results:
            assert r.timing == "accurate"


class TestStructuralErrors:
    def test_deleted_note_is_missed(self):
        reference = _build_reference()
        performance = _perfect_performance(reference)
        del performance[5]
        result = score_performance(reference, performance)
        missed = [r for r in result.notes if r.status == "missed"]
        assert len(missed) == 1
        assert missed[0].ref_index == 5

    def test_inserted_note_is_extra(self):
        reference = _build_reference()
        performance = _perfect_performance(reference)
        performance.insert(6, {"pitch": 90, "onset_sec": 2.75, "dur_sec": 0.1, "velocity": 80})
        result = score_performance(reference, performance)
        extra = [r for r in result.notes if r.status == "extra"]
        assert len(extra) == 1
        assert extra[0].pitch_perf == 90
        # nothing else should be disturbed by the insertion
        assert result.summary.counts["missed"] == 0
        assert result.summary.counts["wrong_pitch"] == 0

    def test_wrong_pitch_stays_matched_not_split(self):
        reference = _build_reference()
        performance = _perfect_performance(reference)
        performance[3]["pitch"] = 61  # ref index 3 is F4=65; play C#4=61 instead, same time
        result = score_performance(reference, performance)

        wrong = [r for r in result.notes if r.ref_index == 3]
        assert len(wrong) == 1
        assert wrong[0].status == "wrong_pitch"
        assert wrong[0].pitch_ref == 65
        assert wrong[0].pitch_perf == 61

        counts = result.summary.counts
        assert counts["missed"] == 0
        assert counts["extra"] == 0
        assert counts["wrong_pitch"] == 1


class TestMetamorphicSymmetry:
    def test_rush_and_drag_of_equal_magnitude_score_the_same(self):
        reference = _build_reference()

        perf_rush = _perfect_performance(reference)
        perf_rush[6]["onset_sec"] -= 0.050
        perf_drag = _perfect_performance(reference)
        perf_drag[6]["onset_sec"] += 0.050

        result_rush = score_performance(reference, perf_rush)
        result_drag = score_performance(reference, perf_drag)
        assert result_rush.summary.score == pytest.approx(result_drag.summary.score, abs=0.01)

    def test_determinism(self):
        reference = _build_reference()
        performance = _perfect_performance(reference)
        performance[2]["pitch"] = 30  # arbitrary perturbation to exercise more code paths
        result_a = score_performance(reference, performance)
        result_b = score_performance(reference, performance)
        assert result_a.to_dict() == result_b.to_dict()


class TestPolyphony:
    def test_chord_matches_regardless_of_input_order(self):
        reference = {
            "title": "Chord Test", "tempo_bpm": 120,
            "tempo_map": [{"beat": 0.0, "bpm": 120.0}],
            "time_signature": "4/4", "key": "C major",
            "duration_beats": 1.0, "duration_sec": 0.5,
            "notes": [
                {"pitch": 60, "name": "C4", "onset_beats": 0.0, "onset_sec": 0.0,
                 "dur_beats": 1.0, "dur_sec": 0.5, "velocity": 80, "hand": "R", "measure": 1},
                {"pitch": 64, "name": "E4", "onset_beats": 0.0, "onset_sec": 0.0,
                 "dur_beats": 1.0, "dur_sec": 0.5, "velocity": 80, "hand": "R", "measure": 1},
                {"pitch": 67, "name": "G4", "onset_beats": 0.0, "onset_sec": 0.0,
                 "dur_beats": 1.0, "dur_sec": 0.5, "velocity": 80, "hand": "R", "measure": 1},
            ],
        }
        # performance plays the same chord, but notes arrive in a different
        # order with a few ms of natural hand-spread between them
        performance = [
            {"pitch": 67, "onset_sec": 0.0, "dur_sec": 0.5, "velocity": 80},
            {"pitch": 60, "onset_sec": 0.01, "dur_sec": 0.5, "velocity": 80},
            {"pitch": 64, "onset_sec": 0.02, "dur_sec": 0.5, "velocity": 80},
        ]
        result = score_performance(reference, performance)
        assert result.summary.counts == {
            "correct": 3, "timing_off": 0, "wrong_pitch": 0, "missed": 0, "extra": 0,
        }


class TestTargetBpm:
    def test_bpm_given_skips_fit_and_uses_absolute_residuals(self):
        reference = _build_reference()
        # performer intends 120bpm (matches reference) -- perfect performance
        performance = _perfect_performance(reference)
        result = score_performance(reference, performance, target_bpm=120)
        assert result.summary.global_tempo_ratio is None
        assert result.summary.counts["correct"] == 12
