#!/usr/bin/env python3
"""Build a generated reference.json directly from a demo recording."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.audio_to_performance.audio_reference import build_audio_reference  # noqa: E402
from backend.audio_to_performance.constrained_verification import load_keyboard_profile  # noqa: E402
from backend.audio_to_performance.keybank import WHITE_KEY_MIDIS  # noqa: E402
from backend.audio_to_performance.reference_constrained import ReferenceConstrainedConfig  # noqa: E402
from backend.hardware import KEYBOARD_RANGE  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract an audio-native reference from a demo recording.",
    )
    parser.add_argument("demo_audio")
    parser.add_argument("-o", "--output", required=True, help="Reference JSON output path.")
    parser.add_argument("--debug-output", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--keyboard-range", type=int, nargs=2, default=list(KEYBOARD_RANGE))
    parser.add_argument("--keyboard-profile", default=None)
    parser.add_argument("--white-keys-only", action="store_true")
    parser.add_argument("--onset-delta", type=float, default=0.22)
    parser.add_argument("--onset-min-confidence", type=float, default=0.12)
    parser.add_argument("--max-pitches-per-onset", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = ReferenceConstrainedConfig(
        keyboard_range=tuple(args.keyboard_range),
        allowed_pitches=WHITE_KEY_MIDIS if args.white_keys_only else None,
        keyboard_profile=load_keyboard_profile(args.keyboard_profile) if args.keyboard_profile else None,
        onset_delta=args.onset_delta,
        onset_min_confidence=args.onset_min_confidence,
        max_pitches_per_onset=args.max_pitches_per_onset,
    )
    reference, debug = build_audio_reference(args.demo_audio, config, title=args.title)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reference, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.debug_output:
        debug_out = Path(args.debug_output)
        debug_out.parent.mkdir(parents=True, exist_ok=True)
        debug_out.write_text(json.dumps(debug, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"reference notes: {len(reference['notes'])}")
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
