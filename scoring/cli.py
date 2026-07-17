"""CLI: python -m scoring reference.json performance.json -o result.json [--bpm 120]"""
from __future__ import annotations

import argparse
import json
import sys

from .config import ScoringConfig
from .score import score_performance


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scoring",
        description="Score a performance against a score_to_reference JSON reference.",
    )
    parser.add_argument("reference", help="Path to reference.json (score_to_reference schema).")
    parser.add_argument("performance", help="Path to performance.json (list of {pitch,onset_sec,...}).")
    parser.add_argument("-o", "--output", help="Path to write result.json. Defaults to stdout.")
    parser.add_argument("--bpm", type=int, default=None, help="Target practice BPM the performer used.")
    args = parser.parse_args(argv)

    with open(args.reference, encoding="utf-8") as f:
        reference = json.load(f)
    with open(args.performance, encoding="utf-8") as f:
        performance = json.load(f)

    result = score_performance(reference, performance, ScoringConfig(), target_bpm=args.bpm)
    output_json = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
    else:
        print(output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
