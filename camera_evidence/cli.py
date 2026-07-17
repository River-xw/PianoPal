"""CLI: python -m camera_evidence result.json --calibration calib.json
       --synthetic --reference reference.json [--error-rate 0.1] [--noise-px 5]
       -o augmented_result.json

--synthetic is the only working mode right now (no camera hardware exists
yet to build/test the real MediaPipe implementation against).
"""
from __future__ import annotations

import argparse
import json
import sys

from .calibration import load_calibration
from .config import CameraEvidenceConfig
from .cross_validate import apply_camera_evidence
from .fingertip_source import MediaPipeFingertipSource, SyntheticFingertipSource


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m camera_evidence",
        description=(
            "Cross-validate a scoring result.json against camera-based fingertip "
            "position evidence to resolve basic-pitch octave errors."
        ),
    )
    parser.add_argument("result", help="Path to scoring's result.json")
    parser.add_argument("--calibration", required=True, help="Path to a calibration JSON (see calibration.calibrate).")
    parser.add_argument("--reference", help="Path to reference.json -- required with --synthetic.")
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Use SyntheticFingertipSource instead of a real camera (no camera hardware exists yet).",
    )
    parser.add_argument("--error-rate", type=float, default=0.0, help="SyntheticFingertipSource: probability of injecting a wrong key reading.")
    parser.add_argument("--noise-px", type=float, default=5.0, help="SyntheticFingertipSource: Gaussian pixel noise stddev.")
    parser.add_argument("--seed", type=int, default=None, help="SyntheticFingertipSource: RNG seed for reproducibility.")
    parser.add_argument("-o", "--output", required=True, help="Path to write the augmented result JSON.")
    args = parser.parse_args(argv)

    with open(args.result, "r", encoding="utf-8") as fh:
        result = json.load(fh)
    calibration = load_calibration(args.calibration)
    config = CameraEvidenceConfig()

    if args.synthetic:
        if not args.reference:
            print("Error: --synthetic requires --reference reference.json", file=sys.stderr)
            return 1
        with open(args.reference, "r", encoding="utf-8") as fh:
            reference = json.load(fh)
        fingertip_source = SyntheticFingertipSource(
            reference, calibration, noise_px=args.noise_px, error_rate=args.error_rate,
            config=config, seed=args.seed,
        )
    else:
        try:
            fingertip_source = MediaPipeFingertipSource()
        except NotImplementedError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            print("Pass --synthetic --reference reference.json to test without real camera hardware.", file=sys.stderr)
            return 1

    augmented = apply_camera_evidence(result, fingertip_source, calibration, config)

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(augmented, fh, indent=2)

    print(f"Augmented result written to {args.output}")
    print(f"camera_evidence_summary: {augmented['summary']['camera_evidence_summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
