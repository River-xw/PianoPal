"""CLI: python -m score_to_reference input.musicxml -o ref.json [--bpm 120]"""
from __future__ import annotations

import argparse
import json
import sys

from .core import convert, to_seconds
from .errors import ScoreReferenceError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m score_to_reference",
        description="Convert a music score (.mid/.musicxml/.xml/.mxl) into a canonical JSON reference.",
    )
    parser.add_argument("input", help="Path to the input score file.")
    parser.add_argument("-o", "--output", help="Path to write the output JSON. Defaults to stdout.")
    parser.add_argument(
        "--bpm", type=int, default=None,
        help="Rescale the reference to this target practice tempo (BPM) before writing it out.",
    )
    args = parser.parse_args(argv)

    try:
        reference = convert(args.input)
        if args.bpm is not None:
            reference = to_seconds(reference, args.bpm)
    except ScoreReferenceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_json = json.dumps(reference, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
    else:
        print(output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
