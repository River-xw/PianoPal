#!/usr/bin/env python3
"""Train a lightweight keyboard timbre profile from recordings."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.audio_to_performance.keyboard_profile import (  # noqa: E402
    KeyboardProfileTrainingConfig,
    train_keyboard_profile,
)
from backend.hardware import KEYBOARD_RANGE  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a PianoPal keyboard timbre profile from audio recordings.",
    )
    parser.add_argument("audio", nargs="+", help="WAV/MP3/M4A/FLAC recordings to train from.")
    parser.add_argument("-o", "--output", required=True, help="Output profile JSON path.")
    parser.add_argument(
        "--keyboard-range",
        type=int,
        nargs=2,
        default=list(KEYBOARD_RANGE),
        metavar=("LOW", "HIGH"),
        help="Physical keyboard MIDI range. Default: PianoPal 37-key range 48 84.",
    )
    parser.add_argument("--min-note-frames", type=int, default=8)
    parser.add_argument("--max-harmonic", type=int, default=10)
    parser.add_argument("--active-rms-percentile", type=float, default=55.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = KeyboardProfileTrainingConfig(
        keyboard_range=tuple(args.keyboard_range),
        min_note_frames=args.min_note_frames,
        max_harmonic=args.max_harmonic,
        active_rms_percentile=args.active_rms_percentile,
    )
    profile = train_keyboard_profile(args.audio, config)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = profile["summary"]
    print(f"wrote {output}")
    print(f"profiled notes: {summary['profiled_notes']} {summary['profiled_midi_pitches']}")
    print(f"kept frames: {summary['kept_frames']} / candidate frames: {summary['candidate_frames']}")


if __name__ == "__main__":
    main()
