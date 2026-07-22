#!/usr/bin/env python3
"""Grade audio without Basic Pitch by verifying expected reference notes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import librosa

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.audio_to_performance.reference_constrained import (  # noqa: E402
    ReferenceConstrainedConfig,
    load_profile_if_present,
    transcribe_onset_first,
    transcribe_reference_guided_onsets,
    transcribe_reference_constrained,
)
from backend.audio_to_performance.keybank import WHITE_KEY_MIDIS  # noqa: E402
from backend.hardware import KEYBOARD_RANGE  # noqa: E402
from backend.score_to_reference import convert as convert_score  # noqa: E402
from backend.scoring import score_performance  # noqa: E402

TARGET_SR = 44100


def load_audio(path: str):
    audio, sr = librosa.load(path, sr=TARGET_SR, mono=True)
    return audio, sr


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/grade_audio_reference_constrained.py",
        description="Grade known-score audio by direct reference-constrained pitch verification.",
    )
    parser.add_argument("reference", help="Reference score: .mid/.midi/.musicxml/.xml/.mxl")
    parser.add_argument("audio", help="Recording (.wav/.mp3/...).")
    parser.add_argument("--keyboard-range", type=int, nargs=2, default=list(KEYBOARD_RANGE), metavar=("LOW", "HIGH"))
    parser.add_argument("--keyboard-profile", default=None, help="Optional profile JSON from scripts/train_keyboard_profile.py.")
    parser.add_argument("--keyboard-profile-weight", type=float, default=0.75)
    parser.add_argument("--white-keys-only", action="store_true")
    parser.add_argument(
        "--mode",
        choices=["reference-guided-onsets", "onset-first", "reference-grid"],
        default="reference-grid",
    )
    parser.add_argument("--onset-window-sec", type=float, default=0.16)
    parser.add_argument("--min-winner-confidence", type=float, default=0.18)
    parser.add_argument("--min-ref-score-ratio", type=float, default=0.65)
    parser.add_argument("--emit-wrong-pitch", action="store_true")
    parser.add_argument("--onset-delta", type=float, default=0.18)
    parser.add_argument("--onset-min-confidence", type=float, default=0.12)
    parser.add_argument("--chord-score-ratio", type=float, default=0.55)
    parser.add_argument("--max-pitches-per-onset", type=int, default=1)
    parser.add_argument("--reference-pitch-score-ratio", type=float, default=0.38)
    parser.add_argument("--fallback-top-pitch", action="store_true", help="Emit the strongest estimated pitch when no nearby reference pitch has enough evidence.")
    parser.add_argument("-o", "--output", required=True, help="Path to write result.json.")
    parser.add_argument("--debug-output", default=None, help="Optional path to write verifier debug JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reference = convert_score(args.reference)
    audio, sr = load_audio(args.audio)
    config = ReferenceConstrainedConfig(
        keyboard_range=tuple(args.keyboard_range),
        allowed_pitches=WHITE_KEY_MIDIS if args.white_keys_only else None,
        keyboard_profile=load_profile_if_present(args.keyboard_profile),
        keyboard_profile_weight=args.keyboard_profile_weight,
        onset_window_sec=args.onset_window_sec,
        min_winner_confidence=args.min_winner_confidence,
        min_ref_score_ratio=args.min_ref_score_ratio,
        emit_wrong_pitch=args.emit_wrong_pitch,
        onset_delta=args.onset_delta,
        onset_min_confidence=args.onset_min_confidence,
        chord_score_ratio=args.chord_score_ratio,
        max_pitches_per_onset=args.max_pitches_per_onset,
        reference_pitch_score_ratio=args.reference_pitch_score_ratio,
        reference_guided_fallback_top_pitch=args.fallback_top_pitch,
    )
    if args.mode == "reference-guided-onsets":
        performance, debug = transcribe_reference_guided_onsets(reference, audio, sr, config)
    elif args.mode == "onset-first":
        performance, debug = transcribe_onset_first(audio, sr, config)
    else:
        performance, debug = transcribe_reference_constrained(reference, audio, sr, config)
    result = score_performance(reference, performance).to_dict()
    result.setdefault("pipeline", {})["audio_to_performance"] = f"reference_constrained:{args.mode}"
    result["pipeline"]["reference_constrained_debug"] = {
        key: value for key, value in debug.items() if key not in {"notes", "events"}
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.debug_output:
        debug_out = Path(args.debug_output)
        debug_out.parent.mkdir(parents=True, exist_ok=True)
        debug_out.write_text(json.dumps(debug, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"mode: {args.mode}")
    print(f"reference notes: {len(reference['notes'])}")
    print(f"emitted performance notes: {debug['emitted_notes']}")
    if "time_scale" in debug:
        print(f"time_scale: {debug['time_scale']}")
    if "detected_onsets" in debug:
        print(f"detected onsets: {debug['detected_onsets']}")
    print(f"score: {result['summary']['score']}  counts {result['summary']['counts']}")
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
