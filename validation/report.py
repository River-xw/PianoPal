"""Builds the aggregate summary + register-bucketed breakdown from a list of
compare.NoteDiff, and aggregates that across multiple pieces (one piece
isn't enough to see whether octave errors cluster in a particular register).
"""
from __future__ import annotations

# (label, lowest MIDI pitch, highest MIDI pitch) -- standard 88-key ranges
REGISTERS = [
    ("bass (A0-B2)", 21, 47),
    ("low-mid (C3-B3)", 48, 59),
    ("mid (C4-B4)", 60, 71),
    ("high (C5-C8)", 72, 108),
]


def register_for_pitch(pitch: int) -> str:
    for name, low, high in REGISTERS:
        if low <= pitch <= high:
            return name
    return "out-of-range"


def build_report(diffs: list, reference_file: str = None) -> dict:
    counts = {"exact_match": 0, "octave_error": 0, "wrong_pitch": 0, "missed": 0, "extra": 0}
    for d in diffs:
        counts[d.status] += 1

    total_ref = counts["exact_match"] + counts["octave_error"] + counts["wrong_pitch"] + counts["missed"]

    octave_details = [
        {
            "ref_pitch": d.ref_pitch, "ref_note": d.ref_name,
            "transcribed_pitch": d.transcribed_pitch, "onset_sec": d.onset_sec,
            "direction": d.octave_direction, "octaves": d.octave_count,
        }
        for d in diffs if d.status == "octave_error"
    ]
    octave_details.sort(key=lambda entry: entry["ref_pitch"])

    register_stats = {}
    for name, low, high in REGISTERS:
        ref_in_register = [d for d in diffs if d.ref_pitch is not None and low <= d.ref_pitch <= high]
        octave_in_register = [d for d in ref_in_register if d.status == "octave_error"]
        total_in_register = len(ref_in_register)
        register_stats[name] = {
            "count": len(octave_in_register),
            "total_in_register": total_in_register,
            "rate": round(len(octave_in_register) / total_in_register, 4) if total_in_register else 0.0,
        }

    report = {
        "total_ref_notes": total_ref,
        "exact_match": counts["exact_match"],
        "octave_errors": counts["octave_error"],
        "wrong_pitch": counts["wrong_pitch"],
        "missed": counts["missed"],
        "extra": counts["extra"],
        "octave_error_rate": round(counts["octave_error"] / total_ref, 4) if total_ref else 0.0,
        "octave_errors_detail": octave_details,
        "octave_errors_by_pitch_range": register_stats,
    }
    if reference_file is not None:
        report["reference_file"] = reference_file
    return report


def aggregate_reports(reports: list) -> dict:
    """Combine per-piece reports (from build_report) into one totals report,
    plus keep the individual per-piece reports for reference.
    """
    total_ref = sum(r["total_ref_notes"] for r in reports)
    exact_match = sum(r["exact_match"] for r in reports)
    octave_errors = sum(r["octave_errors"] for r in reports)
    wrong_pitch = sum(r["wrong_pitch"] for r in reports)
    missed = sum(r["missed"] for r in reports)
    extra = sum(r["extra"] for r in reports)

    register_totals = {}
    for name, _, _ in REGISTERS:
        count = sum(r["octave_errors_by_pitch_range"][name]["count"] for r in reports)
        total_in_register = sum(r["octave_errors_by_pitch_range"][name]["total_in_register"] for r in reports)
        register_totals[name] = {
            "count": count,
            "total_in_register": total_in_register,
            "rate": round(count / total_in_register, 4) if total_in_register else 0.0,
        }

    all_octave_details = []
    for r in reports:
        for entry in r["octave_errors_detail"]:
            all_octave_details.append({**entry, "reference_file": r.get("reference_file")})
    all_octave_details.sort(key=lambda entry: entry["ref_pitch"])

    return {
        "num_pieces": len(reports),
        "total_ref_notes": total_ref,
        "exact_match": exact_match,
        "octave_errors": octave_errors,
        "wrong_pitch": wrong_pitch,
        "missed": missed,
        "extra": extra,
        "octave_error_rate": round(octave_errors / total_ref, 4) if total_ref else 0.0,
        "octave_errors_by_pitch_range": register_totals,
        "octave_errors_detail": all_octave_details,
        "per_piece": reports,
    }
