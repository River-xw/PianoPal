#!/usr/bin/env python3
"""Grade audio without Basic Pitch by verifying expected reference notes."""
from __future__ import annotations

import argparse
import dataclasses
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
    transcribe_reference_dtw,
)
from backend.audio_to_performance.keybank import WHITE_KEY_MIDIS  # noqa: E402
from backend.hardware import KEYBOARD_RANGE  # noqa: E402
from backend.score_to_reference import convert as convert_score  # noqa: E402
from backend.scoring import ScoringConfig, score_performance  # noqa: E402

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
        choices=["reference-guided-onsets", "onset-first", "reference-grid", "reference-dtw"],
        default="reference-dtw",
    )
    parser.add_argument("--onset-window-sec", type=float, default=0.16)
    parser.add_argument("--min-winner-confidence", type=float, default=0.18)
    parser.add_argument("--min-ref-score-ratio", type=float, default=0.65)
    parser.add_argument(
        "--no-emit-wrong-pitch",
        dest="emit_wrong_pitch",
        action="store_false",
        help="Disable wrong-note detection: an unconfirmed expected pitch is reported as missed instead of identifying what was actually played.",
    )
    parser.set_defaults(emit_wrong_pitch=True)
    parser.add_argument("--onset-delta", type=float, default=0.18)
    parser.add_argument("--onset-min-confidence", type=float, default=0.12)
    parser.add_argument("--chord-score-ratio", type=float, default=0.55)
    parser.add_argument("--max-pitches-per-onset", type=int, default=1)
    parser.add_argument("--reference-pitch-score-ratio", type=float, default=0.38)
    parser.add_argument("--fallback-top-pitch", action="store_true", help="Emit the strongest estimated pitch when no nearby reference pitch has enough evidence.")
    parser.add_argument(
        "--restrict-onset-pitches-to-reference",
        action="store_true",
        help=(
            "For --mode onset-first/reference-guided-onsets: only score candidate "
            "pitches that appear somewhere in the reference score (e.g. 11 of 22 "
            "white keys for a typical children's song), instead of the whole "
            "keyboard range. Cuts confusable candidates without assuming WHEN each "
            "pitch occurs, so it stays fully tolerant of tempo rubato -- unlike "
            "reference-grid's time-window narrowing. Trade-off: a genuinely wrong "
            "key the student pressed that's outside this set can still be detected "
            "as an extra/wrong note, but its exact pitch may be misidentified."
        ),
    )
    parser.add_argument("--dtw-pitch-cost-weight", type=float, default=1.5, help="For --mode reference-dtw.")
    parser.add_argument("--dtw-time-weight", type=float, default=0.3, help="For --mode reference-dtw.")
    parser.add_argument("--dtw-gap-penalty", type=float, default=1.2, help="For --mode reference-dtw.")
    parser.add_argument(
        "--score-tol-beat", type=float, default=0.3,
        help=(
            "Final scoring's correct-vs-timing_off cutoff, as a fraction of one beat "
            "(tempo-relative, so it scales with the song's speed) instead of a fixed "
            "ms value. A real student recording has natural tempo looseness that a "
            "tight tolerance (the scoring engine's own default is a fixed 50ms) "
            "punishes even when the right notes were played -- this practice-session "
            "grading path cares primarily about right-vs-wrong notes, not metronome "
            "precision, so it defaults to a much more forgiving 0.3 beat."
        ),
    )
    parser.add_argument("--score-weight-pitch", type=float, default=0.75, help="Overall-score weight on pitch accuracy (right notes vs wrong/missed).")
    parser.add_argument("--score-weight-rhythm", type=float, default=0.25, help="Overall-score weight on rhythm accuracy (coverage-adjusted correct/timing_off ratio).")
    parser.add_argument(
        "--score-weight-timing-stability", type=float, default=0.0,
        help=(
            "Overall-score weight on timing consistency (std of offset_ms). "
            "0 (default) fully disables it: not just excluded from the overall "
            "score, but not computed/shown at all (reports N/A) -- on real mic "
            "recordings its std-of-offset basis is dominated by transcription/"
            "alignment noise rather than genuine unsteadiness, so it wasn't a "
            "reliable signal."
        ),
    )
    parser.add_argument(
        "--score-weight-hand-shape", type=float, default=0.0,
        help=(
            "Overall-score weight on hand-shape/posture (0-100, supplied via "
            "--hand-shape-score). 0 (default) fully disables it -- no posture "
            "classifier is wired into this script; a caller with a real score "
            "(e.g. an orchestrator that ran one) can turn it on."
        ),
    )
    parser.add_argument(
        "--hand-shape-score", type=float, default=None,
        help=(
            "Externally-computed hand-shape/posture score (0-100). "
            "Omit it when motion sensing was unavailable; the overall score "
            "will then be renormalized across the audio-derived scores."
        ),
    )
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
        dtw_pitch_cost_weight=args.dtw_pitch_cost_weight,
        dtw_time_weight=args.dtw_time_weight,
        dtw_gap_penalty=args.dtw_gap_penalty,
    )
    if args.restrict_onset_pitches_to_reference:
        reference_pitches = {int(n["pitch"]) for n in reference["notes"]}
        if config.allowed_pitches is not None:
            reference_pitches &= set(config.allowed_pitches)
        config = dataclasses.replace(config, allowed_pitches=tuple(sorted(reference_pitches)))
    if args.mode == "reference-guided-onsets":
        performance, debug = transcribe_reference_guided_onsets(reference, audio, sr, config)
    elif args.mode == "onset-first":
        performance, debug = transcribe_onset_first(audio, sr, config)
    elif args.mode == "reference-dtw":
        performance, debug = transcribe_reference_dtw(reference, audio, sr, config)
    else:
        performance, debug = transcribe_reference_constrained(reference, audio, sr, config)
    scoring_config = ScoringConfig(
        tol_beat=args.score_tol_beat,
        score_weight_pitch=args.score_weight_pitch,
        score_weight_rhythm=args.score_weight_rhythm,
        score_weight_timing_stability=args.score_weight_timing_stability,
        score_weight_hand_shape=args.score_weight_hand_shape,
    )
    result = score_performance(
        reference, performance, scoring_config, hand_shape_score=args.hand_shape_score
    ).to_dict()
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
