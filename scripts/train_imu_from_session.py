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
            "a baseline classifier from all hand sensor streams."
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
    )
    model = train_nearest_centroid_model(rows)
    model["training_config"] = {
        "session_id": args.session_id,
        "pre_sec": args.pre_sec,
        "post_sec": args.post_sec,
        "onset_merge_sec": args.onset_merge_sec,
        "imu_time_offset_sec": args.imu_time_offset_sec,
        "feature_source": "all_hand_sensors",
        "audio_source": "backend.audio_to_performance",
    }

    write_jsonl(paths["features_output"], rows)
    write_json(paths["model_output"], model)

    label_counts: dict[str, int] = {}
    for row in rows:
        label_counts[row["label"]] = label_counts.get(row["label"], 0) + 1

    print(f"events: {len(events)}")
    print(f"feature rows: {len(rows)} -> {paths['features_output']}")
    print(f"model: {paths['model_output']}")
    print(f"labels: {json.dumps(label_counts, ensure_ascii=False, sort_keys=True)}")
    print(f"training accuracy: {model['metrics']['training_accuracy']}")
    return 0


def _resolve_paths(args: argparse.Namespace) -> dict[str, Path | None]:
    session_dir = args.session_dir
    audio = args.audio
    performance_json = args.performance_json
    left_imu = args.left_imu
    right_imu = args.right_imu

    if session_dir is not None:
        audio = audio or session_dir / "audio.wav"
        left_imu = left_imu or session_dir / "imu_left.jsonl"
        right_imu = right_imu or session_dir / "imu_right.jsonl"

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
        "features_output": features_output,
        "model_output": model_output,
    }


if __name__ == "__main__":
    raise SystemExit(main())
