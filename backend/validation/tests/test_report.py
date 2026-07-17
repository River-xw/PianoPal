"""Tests for report.py: register bucketing and summary/aggregation building."""
from __future__ import annotations

from backend.validation.compare import NoteDiff
from backend.validation.report import aggregate_reports, build_report, register_for_pitch


class TestRegisterForPitch:
    def test_bass(self):
        assert register_for_pitch(21) == "bass (A0-B2)"   # A0, lowest key
        assert register_for_pitch(47) == "bass (A0-B2)"   # B2

    def test_low_mid(self):
        assert register_for_pitch(48) == "low-mid (C3-B3)"  # C3
        assert register_for_pitch(59) == "low-mid (C3-B3)"  # B3

    def test_mid(self):
        assert register_for_pitch(60) == "mid (C4-B4)"  # middle C
        assert register_for_pitch(71) == "mid (C4-B4)"  # B4

    def test_high(self):
        assert register_for_pitch(72) == "high (C5-C8)"   # C5
        assert register_for_pitch(108) == "high (C5-C8)"  # C8, highest key

    def test_out_of_range(self):
        assert register_for_pitch(10) == "out-of-range"
        assert register_for_pitch(120) == "out-of-range"


def _diff(status, ref_pitch=None, transcribed_pitch=None, onset_sec=0.0, direction=None, octaves=None):
    return NoteDiff(
        ref_pitch=ref_pitch, ref_name=f"p{ref_pitch}" if ref_pitch else None,
        transcribed_pitch=transcribed_pitch, onset_sec=onset_sec, status=status,
        octave_direction=direction, octave_count=octaves,
    )


class TestBuildReport:
    def test_counts_and_rate(self):
        diffs = [
            _diff("exact_match", ref_pitch=60, transcribed_pitch=60),
            _diff("octave_error", ref_pitch=64, transcribed_pitch=76, direction="up", octaves=1),
            _diff("wrong_pitch", ref_pitch=67, transcribed_pitch=69),
            _diff("missed", ref_pitch=71),
            _diff("extra", transcribed_pitch=90),
        ]
        report = build_report(diffs)
        assert report["total_ref_notes"] == 4  # exact+octave+wrong+missed, NOT extra
        assert report["exact_match"] == 1
        assert report["octave_errors"] == 1
        assert report["wrong_pitch"] == 1
        assert report["missed"] == 1
        assert report["extra"] == 1
        assert report["octave_error_rate"] == 0.25

    def test_octave_errors_land_in_the_right_register_bucket(self):
        diffs = [
            _diff("octave_error", ref_pitch=30, transcribed_pitch=42, direction="up", octaves=1),  # bass
            _diff("octave_error", ref_pitch=65, transcribed_pitch=77, direction="up", octaves=1),   # mid
            _diff("exact_match", ref_pitch=30, transcribed_pitch=30),  # another bass note, no error
        ]
        report = build_report(diffs)
        buckets = report["octave_errors_by_pitch_range"]
        assert buckets["bass (A0-B2)"]["count"] == 1
        assert buckets["bass (A0-B2)"]["total_in_register"] == 2
        assert buckets["mid (C4-B4)"]["count"] == 1
        assert buckets["mid (C4-B4)"]["total_in_register"] == 1
        assert buckets["high (C5-C8)"]["count"] == 0

    def test_empty_diffs_no_crash(self):
        report = build_report([])
        assert report["total_ref_notes"] == 0
        assert report["octave_error_rate"] == 0.0


class TestAggregateReports:
    def test_sums_across_pieces(self):
        r1 = build_report([
            _diff("exact_match", ref_pitch=60, transcribed_pitch=60),
            _diff("octave_error", ref_pitch=64, transcribed_pitch=76, direction="up", octaves=1),
        ], reference_file="piece1.mid")
        r2 = build_report([
            _diff("octave_error", ref_pitch=65, transcribed_pitch=77, direction="up", octaves=1),
            _diff("missed", ref_pitch=67),
        ], reference_file="piece2.mid")

        agg = aggregate_reports([r1, r2])
        assert agg["num_pieces"] == 2
        assert agg["total_ref_notes"] == 4
        assert agg["octave_errors"] == 2
        assert agg["missed"] == 1
        assert len(agg["octave_errors_detail"]) == 2
        assert agg["per_piece"] == [r1, r2]
