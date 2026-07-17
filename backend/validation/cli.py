"""CLI: python -m backend.validation.roundtrip reference.mid --soundfont path/to.sf2
       [-o report.json] [--onset-tol-ms 100]

Accepts one or more reference files, or a directory (recursed for
.mid/.midi/.musicxml/.xml/.mxl files) -- aggregates stats across all of them,
since one piece isn't enough to see whether octave errors cluster by register.
"""
from __future__ import annotations

import argparse
import json
import sys

from .errors import ValidationError
from .report import aggregate_reports
from .roundtrip import collect_reference_files, run_roundtrip


def _print_human_report(report: dict, title: str) -> None:
    print(f"\n=== {title} ===")
    print(f"total reference notes: {report['total_ref_notes']}")
    print(f"  exact_match:  {report['exact_match']}")
    print(f"  octave_error: {report['octave_errors']}  (rate: {report['octave_error_rate']:.2%})")
    print(f"  wrong_pitch:  {report['wrong_pitch']}")
    print(f"  missed:       {report['missed']}")
    print(f"  extra:        {report['extra']}")

    print("\noctave errors by register:")
    for register, stats in report["octave_errors_by_pitch_range"].items():
        print(f"  {register:20s} {stats['count']:4d} / {stats['total_in_register']:4d}  (rate: {stats['rate']:.2%})")

    if report["octave_errors_detail"]:
        print("\noctave errors, sorted by pitch:")
        print(f"  {'ref_pitch':>9s} {'ref_note':>9s} {'transcribed':>12s} {'onset_sec':>10s} {'direction':>10s}")
        for entry in report["octave_errors_detail"]:
            file_tag = f" ({entry['reference_file']})" if "reference_file" in entry else ""
            print(
                f"  {entry['ref_pitch']:>9d} {entry['ref_note'] or '?':>9s} "
                f"{entry['transcribed_pitch']:>12d} {entry['onset_sec']:>10.3f} "
                f"{entry['direction']:>10s}{file_tag}"
            )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.validation.roundtrip",
        description=(
            "Round-trip validation: synthesize reference MIDI with a real piano "
            "soundfont, transcribe it back, and report octave errors by register."
        ),
    )
    parser.add_argument("reference", nargs="+", help="Reference .mid/.musicxml file(s), or a directory to recurse.")
    parser.add_argument("--soundfont", required=True, help="Path to a real piano soundfont (e.g. FluidR3_GM.sf2).")
    parser.add_argument("-o", "--output", help="Path to write the aggregated report JSON.")
    parser.add_argument("--onset-tol-ms", type=float, default=100.0, help="Onset matching tolerance in ms.")
    parser.add_argument("--save-synth-dir", default=None, help="Directory to save each piece's synthesized WAV.")
    parser.add_argument("--save-midi-dir", default=None, help="Directory to save each piece's transcribed MIDI.")
    args = parser.parse_args(argv)

    files = collect_reference_files(args.reference)
    if not files:
        print("Error: no .mid/.midi/.musicxml/.xml/.mxl files found in the given path(s).", file=sys.stderr)
        return 1

    print(f"Found {len(files)} reference file(s):")
    for f in files:
        print(f"  {f}")

    from pathlib import Path

    if args.save_synth_dir:
        Path(args.save_synth_dir).mkdir(parents=True, exist_ok=True)
    if args.save_midi_dir:
        Path(args.save_midi_dir).mkdir(parents=True, exist_ok=True)

    reports = []
    for f in files:
        stem = Path(f).stem
        save_wav = str(Path(args.save_synth_dir) / f"{stem}.wav") if args.save_synth_dir else None
        save_mid = str(Path(args.save_midi_dir) / f"{stem}_transcribed.mid") if args.save_midi_dir else None
        try:
            report = run_roundtrip(
                f, args.soundfont, onset_tol_sec=args.onset_tol_ms / 1000.0,
                save_synth_wav=save_wav, save_transcribed_midi=save_mid,
            )
        except ValidationError as exc:
            print(f"Error processing '{f}': {exc}", file=sys.stderr)
            return 1
        _print_human_report(report, title=f)
        reports.append(report)

    aggregated = aggregate_reports(reports)
    if len(reports) > 1:
        _print_human_report(aggregated, title=f"AGGREGATE ({len(reports)} pieces)")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(aggregated, fh, indent=2, ensure_ascii=False)
        print(f"\nFull report saved to {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
