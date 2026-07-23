"""Train an IMU keypress classifier from one audio-aligned session."""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.sensors.training import (  # noqa: E402
    build_feature_rows,
    load_audio_start_unix_ms,
    load_event_labels,
    load_hand_packets,
    load_performance_json,
    performance_to_onset_events,
    train_nearest_centroid_model,
    write_json,
    write_jsonl,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/train_imu_from_session.py",
        description=(
            "Use backend audio transcription to trigger IMU windows, then train "
            "a hand-independent baseline classifier from all sensors on each hand."
        ),
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument(
        "--session-dir",
        type=Path,
        default=None,
        help="Directory containing audio.wav, imu_left.jsonl, and imu_right.jsonl.",
    )
    parser.add_argument("--audio", type=Path, default=None, help="audio.wav path.")
    parser.add_argument(
        "--performance-json",
        type=Path,
        default=None,
        help="Existing backend audio_to_performance JSON. If omitted, --audio is transcribed.",
    )
    parser.add_argument("--left-imu", type=Path, default=None)
    parser.add_argument("--right-imu", type=Path, default=None)
    parser.add_argument(
        "--timing-json",
        type=Path,
        default=None,
        help=(
            "Runtime timing.json. With --session-dir, it is detected automatically "
            "when present."
        ),
    )
    parser.add_argument(
        "--labels",
        type=Path,
        required=True,
        help="JSON labels, one label per audio onset event.",
    )
    parser.add_argument("--features-output", type=Path, default=None)
    parser.add_argument("--model-output", type=Path, default=None)
    parser.add_argument("--save-performance-json", type=Path, default=None)
    parser.add_argument("--pre-sec", type=float, default=0.5)
    parser.add_argument("--post-sec", type=float, default=0.3)
    parser.add_argument(
        "--onset-merge-sec",
        type=float,
        default=0.03,
        help="Merge notes this close into one physical keypress/chord event.",
    )
    parser.add_argument(
        "--imu-time-offset-sec",
        type=float,
        default=0.0,
        help="Add this offset when mapping audio onsets to IMU device timestamps.",
    )
    parser.add_argument(
        "--min-valid-samples-per-hand",
        type=int,
        default=3,
        help="Minimum cleaned IMU packets required for one hand/event sample.",
    )
    parser.add_argument(
        "--min-valid-ratio",
        type=float,
        default=0.8,
        help="Minimum valid-packet fraction required per hand and event.",
    )
    parser.add_argument("--onset-thresh", type=float, default=0.6)
    parser.add_argument("--frame-thresh", type=float, default=0.4)
    parser.add_argument("--min-note-length-ms", type=float, default=58.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = _resolve_paths(args)

    if paths["performance_json"] is not None:
        performance = load_performance_json(paths["performance_json"])
    else:
        from backend.audio_to_performance.config import AudioToPerformanceConfig
        from backend.audio_to_performance.pipeline import transcribe

        config = AudioToPerformanceConfig(
            onset_threshold=args.onset_thresh,
            frame_threshold=args.frame_thresh,
            minimum_note_length_ms=args.min_note_length_ms,
        )
        performance = transcribe(wav_path=str(paths["audio"]), config=config)
        if args.save_performance_json is not None:
            args.save_performance_json.parent.mkdir(parents=True, exist_ok=True)
            args.save_performance_json.write_text(
                json.dumps(performance, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    events = performance_to_onset_events(performance, merge_sec=args.onset_merge_sec)
    labels = load_event_labels(args.labels, event_count=len(events))
    left_packets = load_hand_packets(paths["left_imu"])
    right_packets = load_hand_packets(paths["right_imu"])
    audio_started_at_unix_ms = (
        load_audio_start_unix_ms(paths["timing_json"])
        if paths["timing_json"] is not None
        else None
    )
    if args.min_valid_samples_per_hand < 1:
        raise SystemExit("--min-valid-samples-per-hand must be at least 1")
    if not 0.0 <= args.min_valid_ratio <= 1.0:
        raise SystemExit("--min-valid-ratio must be between 0 and 1")

    rows = build_feature_rows(
        session_id=args.session_id,
        performance_notes=performance,
        left_packets=left_packets,
        right_packets=right_packets,
        labels=labels,
        pre_sec=args.pre_sec,
        post_sec=args.post_sec,
        onset_merge_sec=args.onset_merge_sec,
        imu_time_offset_sec=args.imu_time_offset_sec,
        audio_started_at_unix_ms=audio_started_at_unix_ms,
        min_valid_samples_per_hand=args.min_valid_samples_per_hand,
        min_valid_ratio=args.min_valid_ratio,
    )
    model = train_nearest_centroid_model(rows)
    model["training_config"] = {
        "session_id": args.session_id,
        "pre_sec": args.pre_sec,
        "post_sec": args.post_sec,
        "onset_merge_sec": args.onset_merge_sec,
        "imu_time_offset_sec": args.imu_time_offset_sec,
        "min_valid_samples_per_hand": args.min_valid_samples_per_hand,
        "min_valid_ratio": args.min_valid_ratio,
        "timing_json": str(paths["timing_json"]) if paths["timing_json"] else None,
        "time_alignment": (
            "median_received_minus_device_timestamp"
            if audio_started_at_unix_ms is not None
            else "legacy_first_packet"
        ),
        "feature_source": "all_hand_sensors",
        "hand_strategy": "pooled_independent_samples",
        "audio_source": "backend.audio_to_performance",
    }

    write_jsonl(paths["features_output"], rows)
    write_json(paths["model_output"], model)

    label_counts: dict[str, int] = {}
    hand_counts: dict[str, int] = {}
    for row in rows:
        label_counts[row["label"]] = label_counts.get(row["label"], 0) + 1
        hand_counts[row["hand"]] = hand_counts.get(row["hand"], 0) + 1

    print(f"events: {len(events)}")
    print(f"hand samples: {len(rows)} -> {paths['features_output']}")
    print(f"model: {paths['model_output']}")
    print(f"labels: {json.dumps(label_counts, ensure_ascii=False, sort_keys=True)}")
    print(f"hands: {json.dumps(hand_counts, sort_keys=True)} (metadata only)")
    print(f"time alignment: {model['training_config']['time_alignment']}")
    print(
        "quality filter: "
        f"{model['metrics']['training_samples']} usable, "
        f"{model['metrics']['dropped_samples']} dropped"
    )
    print(f"training accuracy: {model['metrics']['training_accuracy']}")
    return 0


def _resolve_paths(args: argparse.Namespace) -> dict[str, Path | None]:
    session_dir = args.session_dir
    audio = args.audio
    performance_json = args.performance_json
    left_imu = args.left_imu
    right_imu = args.right_imu
    timing_json = args.timing_json

    if session_dir is not None:
        audio = audio or session_dir / "audio.wav"
        left_imu = left_imu or session_dir / "imu_left.jsonl"
        right_imu = right_imu or session_dir / "imu_right.jsonl"
        if timing_json is None:
            candidate_timing_json = session_dir / "timing.json"
            if candidate_timing_json.exists():
                timing_json = candidate_timing_json

    if performance_json is None and audio is None:
        raise SystemExit("provide --performance-json, or provide --audio/--session-dir")
    if left_imu is None or right_imu is None:
        raise SystemExit("provide --left-imu/--right-imu, or provide --session-dir")

    artifacts_dir = ROOT / "data" / "artifacts" / "sessions" / args.session_id
    features_output = args.features_output or artifacts_dir / "imu_keypress_features.jsonl"
    model_output = args.model_output or ROOT / "models" / "gesture" / f"{args.session_id}_hand_imu_model.json"

    return {
        "audio": audio,
        "performance_json": performance_json,
        "left_imu": left_imu,
        "right_imu": right_imu,
        "timing_json": timing_json,
        "features_output": features_output,
        "model_output": model_output,
    }


if __name__ == "__main__":
    raise SystemExit(main())
