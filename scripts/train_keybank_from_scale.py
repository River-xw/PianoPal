#!/usr/bin/env python3
"""Train a BF-3738C keybank from a left-to-right scale recording."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.audio_to_performance.keybank import (  # noqa: E402
    ScaleKeybankTrainingConfig,
    keybank_profile,
    train_keybank_from_scale,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Split a left-to-right BF-3738C scale recording into labeled key samples. "
            "Currently supports the 22 white keys in the assumed C3..C6 range."
        ),
    )
    parser.add_argument("audio", help="Scale recording, played from left to right.")
    parser.add_argument("-o", "--output", required=True, help="Output keybank JSON path.")
    parser.add_argument("--samples-dir", required=True, help="Directory for per-key WAV samples.")
    parser.add_argument("--keys", choices=["white"], default="white")
    parser.add_argument("--profile-output", default=None, help="Optional standalone keyboard profile JSON.")
    parser.add_argument("--min-onset-gap-sec", type=float, default=0.9)
    parser.add_argument("--onset-delta", type=float, default=0.08)
    parser.add_argument("--max-sample-sec", type=float, default=1.45)
    parser.add_argument("--normalize-peak", type=float, default=0.75)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = ScaleKeybankTrainingConfig(
        min_onset_gap_sec=args.min_onset_gap_sec,
        onset_delta=args.onset_delta,
        max_sample_sec=args.max_sample_sec,
        normalize_peak=args.normalize_peak,
    )
    keybank = train_keybank_from_scale(
        args.audio,
        output_path=args.output,
        samples_dir=args.samples_dir,
        keys=args.keys,
        config=config,
    )

    if args.profile_output:
        profile_out = Path(args.profile_output)
        profile_out.parent.mkdir(parents=True, exist_ok=True)
        profile_out.write_text(
            json.dumps(keybank_profile(keybank), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    summary = keybank["summary"]
    onset_info = keybank["onset_detection"]
    print(f"wrote keybank: {args.output}")
    print(f"wrote samples: {args.samples_dir}")
    if args.profile_output:
        print(f"wrote profile: {args.profile_output}")
    print(
        "onsets: "
        f"{onset_info['raw_onset_count']} raw -> "
        f"{onset_info['deduplicated_onset_count']} deduplicated -> "
        f"{len(keybank['samples'])} labeled samples"
    )
    print(
        f"diagnostic flags: {summary['diagnostic_flag_count']} "
        f"{summary['diagnostic_flags']}"
    )
    print(f"midi pitches: {keybank['expected_midi_pitches']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
