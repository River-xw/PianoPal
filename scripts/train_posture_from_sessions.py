"""Train a left-hand IMU posture classifier from session folder labels."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.sensors.training import (  # noqa: E402
    extract_window_features,
    load_hand_packets,
    write_json,
    write_jsonl,
)
from backend.sensors.schemas import RawHandSensorPacket, SensorReading  # noqa: E402


KNOWN_LABELS = (
    "normal",
    "finger_collapse",
    "high_lift_tap",
    "wrist_arch",
    "wrist_collapse",
    "wrist_shake",
)


@dataclass(frozen=True)
class CleanedPacket:
    packet: RawHandSensorPacket
    valid: bool
    reasons: tuple[str, ...]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/train_posture_from_sessions.py",
        description=(
            "Clean left-hand IMU sessions, label them from folder names, "
            "make sliding-window features, and train a supervised classifier."
        ),
    )
    parser.add_argument(
        "--sessions-root",
        type=Path,
        default=ROOT / "data" / "training_collection" / "raw" / "sessions",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            ROOT / "data" / "training_collection" / "artifacts"
            / "gesture_training" / "left_hand_posture"
        ),
    )
    parser.add_argument(
        "--model-output",
        type=Path,
        default=ROOT / "models" / "gesture" / "left_hand_posture_classifier.joblib",
    )
    parser.add_argument(
        "--portable-model-output",
        type=Path,
        default=ROOT / "models" / "gesture" / "left_hand_posture_classifier.json",
    )
    parser.add_argument("--window-sec", type=float, default=2.0)
    parser.add_argument("--stride-sec", type=float, default=0.5)
    parser.add_argument("--min-valid-samples", type=int, default=4)
    parser.add_argument("--min-valid-ratio", type=float, default=0.8)
    parser.add_argument("--max-gap-ms", type=int, default=3000)
    parser.add_argument(
        "--normal-class-weight",
        type=float,
        default=1.25,
        help=(
            "Weight for the normal class. Values above 1 make the classifier "
            "more conservative about reporting posture errors."
        ),
    )
    parser.add_argument("--random-state", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.window_sec <= 0:
        raise SystemExit("--window-sec must be positive")
    if args.stride_sec <= 0:
        raise SystemExit("--stride-sec must be positive")
    if args.min_valid_samples < 1:
        raise SystemExit("--min-valid-samples must be at least 1")
    if not 0.0 <= args.min_valid_ratio <= 1.0:
        raise SystemExit("--min-valid-ratio must be between 0 and 1")
    if args.normal_class_weight <= 0.0:
        raise SystemExit("--normal-class-weight must be positive")

    rows, report = build_labeled_feature_rows(
        sessions_root=args.sessions_root,
        window_ms=int(args.window_sec * 1000),
        stride_ms=int(args.stride_sec * 1000),
        min_valid_samples=args.min_valid_samples,
        min_valid_ratio=args.min_valid_ratio,
        max_gap_ms=args.max_gap_ms,
    )
    if not rows:
        raise SystemExit("no usable left-hand training windows were produced")

    model_info = train_sklearn_model(
        rows,
        model_output=args.model_output,
        portable_model_output=args.portable_model_output,
        normal_class_weight=args.normal_class_weight,
        random_state=args.random_state,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    features_output = args.output_dir / "left_hand_posture_windows.jsonl"
    report_output = args.output_dir / "cleaning_and_label_report.json"
    label_manifest_output = args.output_dir / "session_labels.json"
    model_report_output = args.output_dir / "model_report.json"

    write_jsonl(features_output, rows)
    write_json(report_output, report)
    write_json(label_manifest_output, {"sessions": report["session_labels"]})
    write_json(model_report_output, model_info)

    print(f"sessions used: {report['summary']['used_sessions']}")
    print(f"windows: {report['summary']['usable_windows']} usable / {report['summary']['raw_windows']} raw")
    print(f"labels: {json.dumps(report['summary']['usable_windows_by_label'], sort_keys=True)}")
    print(f"features: {features_output}")
    print(f"cleaning report: {report_output}")
    print(f"model: {args.model_output}")
    print(f"portable model: {args.portable_model_output}")
    print(f"model report: {model_report_output}")
    print(f"cv accuracy: {model_info['metrics'].get('cv_accuracy')}")
    print(f"cv balanced accuracy: {model_info['metrics'].get('cv_balanced_accuracy')}")
    return 0


def build_labeled_feature_rows(
    *,
    sessions_root: Path,
    window_ms: int,
    stride_ms: int,
    min_valid_samples: int,
    min_valid_ratio: float,
    max_gap_ms: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    session_reports: list[dict[str, Any]] = []
    session_labels: list[dict[str, str]] = []

    for session_dir in sorted(path for path in sessions_root.iterdir() if path.is_dir()):
        session_id = session_dir.name
        label = infer_label(session_id)
        left_imu = session_dir / "imu_left.jsonl"

        if label is None:
            session_reports.append(
                {
                    "session_id": session_id,
                    "used": False,
                    "reason": "unrecognized_label",
                }
            )
            continue
        if not left_imu.exists():
            session_reports.append(
                {
                    "session_id": session_id,
                    "label": label,
                    "used": False,
                    "reason": "missing_imu_left_jsonl",
                }
            )
            continue

        packets = load_hand_packets(left_imu)
        cleaned = [clean_packet(packet) for packet in packets]
        segments = split_segments(
            cleaned,
            max_gap_ms=max_gap_ms,
        )
        session_rows = []
        for segment_index, segment in enumerate(segments):
            session_rows.extend(
                window_segment(
                    session_id=session_id,
                    label=label,
                    segment_index=segment_index,
                    segment=segment,
                    window_ms=window_ms,
                    stride_ms=stride_ms,
                    min_valid_samples=min_valid_samples,
                    min_valid_ratio=min_valid_ratio,
                )
            )

        valid_packets = sum(1 for item in cleaned if item.valid)
        invalid_reasons = Counter(
            reason
            for item in cleaned
            for reason in item.reasons
        )
        usable_windows = [row for row in session_rows if row["usable_for_training"]]
        rows.extend(usable_windows)
        session_reports.append(
            {
                "session_id": session_id,
                "label": label,
                "used": bool(usable_windows),
                "left_packet_count": len(packets),
                "valid_left_packet_count": valid_packets,
                "invalid_left_packet_count": len(packets) - valid_packets,
                "invalid_packet_reasons": dict(sorted(invalid_reasons.items())),
                "segment_count": len(segments),
                "raw_windows": len(session_rows),
                "usable_windows": len(usable_windows),
                "dropped_windows": len(session_rows) - len(usable_windows),
            }
        )
        session_labels.append({"session_id": session_id, "label": label})

    usable_by_label = Counter(row["label"] for row in rows)
    raw_windows_by_label: Counter[str] = Counter()
    for item in session_reports:
        if item.get("label"):
            raw_windows_by_label[str(item["label"])] += int(item.get("raw_windows", 0))

    report = {
        "schema_version": "left_hand_posture_cleaning_report_v1",
        "sessions_root": str(sessions_root),
        "label_source": "session_folder_name",
        "hand_strategy": "left_hand_only_right_hand_ignored",
        "known_labels": list(KNOWN_LABELS),
        "cleaning_rules": {
            "drop_packet_when_any_required_sensor_is_all_zero": True,
            "drop_packet_when_external_mpu_value_is_exact_int16_saturation": True,
            "split_segment_on_timestamp_or_sequence_reset": True,
            "split_segment_on_gap_ms_over": max_gap_ms,
            "window_ms": window_ms,
            "stride_ms": stride_ms,
            "min_valid_samples": min_valid_samples,
            "min_valid_ratio": min_valid_ratio,
        },
        "summary": {
            "candidate_sessions": len(session_reports),
            "used_sessions": sum(1 for item in session_reports if item.get("used")),
            "usable_windows": len(rows),
            "raw_windows": sum(int(item.get("raw_windows", 0)) for item in session_reports),
            "usable_windows_by_label": dict(sorted(usable_by_label.items())),
            "raw_windows_by_label": dict(sorted(raw_windows_by_label.items())),
        },
        "session_labels": session_labels,
        "sessions": session_reports,
    }
    return rows, report


def infer_label(session_id: str) -> str | None:
    name = session_id
    if name.startswith("sess_"):
        name = name[5:]
    parts = name.split("_")
    while parts and parts[-1].isdigit():
        parts.pop()
    label = "_".join(parts)
    return label if label in KNOWN_LABELS else None


def clean_packet(packet: RawHandSensorPacket) -> CleanedPacket:
    reasons: list[str] = []
    required = {
        "fingertip": packet.fingertip,
        "hand_back": packet.hand_back,
        "wrist": packet.wrist,
    }
    for sensor_name, reading in required.items():
        if reading_is_all_zero(reading):
            reasons.append(f"{sensor_name}_all_zero")
    for sensor_name in ("fingertip", "hand_back"):
        reading = getattr(packet, sensor_name)
        if reading_has_saturated_int16(reading):
            reasons.append(f"{sensor_name}_int16_saturation")
    return CleanedPacket(packet=packet, valid=not reasons, reasons=tuple(reasons))


def reading_is_all_zero(reading: SensorReading) -> bool:
    vectors = [reading.accel]
    if reading.gyro is not None:
        vectors.append(reading.gyro)
    return all(vector.x == 0.0 and vector.y == 0.0 and vector.z == 0.0 for vector in vectors)


def reading_has_saturated_int16(reading: SensorReading) -> bool:
    vectors = [reading.accel]
    if reading.gyro is not None:
        vectors.append(reading.gyro)
    return any(
        abs(float(value)) >= 32760.0
        for vector in vectors
        for value in (vector.x, vector.y, vector.z)
    )


def split_segments(
    cleaned_packets: list[CleanedPacket],
    *,
    max_gap_ms: int,
) -> list[list[CleanedPacket]]:
    if not cleaned_packets:
        return []

    segments: list[list[CleanedPacket]] = []
    current = [cleaned_packets[0]]
    for previous, item in zip(cleaned_packets, cleaned_packets[1:]):
        previous_packet = previous.packet
        packet = item.packet
        reset = (
            packet.device_timestamp_ms <= previous_packet.device_timestamp_ms
            or packet.sequence_number <= previous_packet.sequence_number
        )
        large_gap = packet.device_timestamp_ms - previous_packet.device_timestamp_ms > max_gap_ms
        if reset or large_gap:
            segments.append(current)
            current = []
        current.append(item)
    if current:
        segments.append(current)
    return segments


def window_segment(
    *,
    session_id: str,
    label: str,
    segment_index: int,
    segment: list[CleanedPacket],
    window_ms: int,
    stride_ms: int,
    min_valid_samples: int,
    min_valid_ratio: float,
) -> list[dict[str, Any]]:
    if not segment:
        return []
    start_ms = segment[0].packet.device_timestamp_ms
    end_ms = segment[-1].packet.device_timestamp_ms
    rows = []
    window_index = 0
    current_start = start_ms

    while current_start + window_ms <= end_ms:
        current_end = current_start + window_ms
        window = [
            item
            for item in segment
            if current_start <= item.packet.device_timestamp_ms <= current_end
        ]
        valid_packets = [item.packet for item in window if item.valid]
        raw_count = len(window)
        valid_ratio = len(valid_packets) / raw_count if raw_count else 0.0
        quality_reasons = []
        if len(valid_packets) < min_valid_samples:
            quality_reasons.append(f"valid_samples_below_{min_valid_samples}")
        if valid_ratio < min_valid_ratio:
            quality_reasons.append(f"valid_ratio_below_{min_valid_ratio:g}")

        rows.append(
            {
                "schema_version": "left_hand_posture_window_v1",
                "session_id": session_id,
                "label": label,
                "hand": "L",
                "segment_index": segment_index,
                "window_index": window_index,
                "window_start_device_ms": int(current_start),
                "window_end_device_ms": int(current_end),
                "window_duration_sec": round(window_ms / 1000.0, 6),
                "raw_sample_count": raw_count,
                "sample_count": len(valid_packets),
                "invalid_sample_count": raw_count - len(valid_packets),
                "valid_ratio": round(valid_ratio, 4),
                "usable_for_training": not quality_reasons,
                "quality_reasons": quality_reasons,
                "features": extract_window_features(valid_packets, prefix=""),
            }
        )
        window_index += 1
        current_start += stride_ms
    return rows


def train_sklearn_model(
    rows: list[dict[str, Any]],
    *,
    model_output: Path,
    portable_model_output: Path,
    normal_class_weight: float,
    random_state: int,
) -> dict[str, Any]:
    try:
        import joblib
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.metrics import (
            accuracy_score,
            balanced_accuracy_score,
            classification_report,
            confusion_matrix,
        )
        from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict
        from sklearn.pipeline import Pipeline
    except ImportError as exc:
        raise RuntimeError("scikit-learn and joblib are required to train this model") from exc

    feature_dicts = [row["features"] for row in rows]
    labels = [row["label"] for row in rows]
    groups = [row["session_id"] for row in rows]
    label_counts = Counter(labels)
    class_weight = {
        label: (float(normal_class_weight) if label == "normal" else 1.0)
        for label in label_counts
    }
    group_counts_by_label: dict[str, set[str]] = defaultdict(set)
    for label, group in zip(labels, groups):
        group_counts_by_label[label].add(group)

    min_label_groups = min(len(groups_for_label) for groups_for_label in group_counts_by_label.values())
    n_splits = max(2, min(5, min_label_groups))

    model = Pipeline(
        steps=[
            ("features", DictVectorizer(sparse=False)),
            (
                "classifier",
                RandomForestClassifier(
                    n_estimators=300,
                    max_depth=None,
                    min_samples_leaf=2,
                    class_weight=class_weight,
                    random_state=random_state,
                    n_jobs=-1,
                ),
            ),
        ]
    )

    cv_predictions = None
    cv_report: dict[str, Any] | None = None
    cv_confusion: dict[str, Any] | None = None
    if n_splits >= 2:
        splitter = StratifiedGroupKFold(
            n_splits=n_splits,
            shuffle=True,
            random_state=random_state,
        )
        cv_predictions = cross_val_predict(
            model,
            feature_dicts,
            labels,
            groups=groups,
            cv=splitter,
        )
        label_order = sorted(label_counts)
        cv_report = classification_report(
            labels,
            cv_predictions,
            labels=label_order,
            output_dict=True,
            zero_division=0,
        )
        cv_confusion = {
            "labels": label_order,
            "matrix": confusion_matrix(labels, cv_predictions, labels=label_order).tolist(),
        }

    model.fit(feature_dicts, labels)
    model_output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_output)
    export_portable_random_forest_model(model, portable_model_output)

    feature_names = list(model.named_steps["features"].get_feature_names_out())
    metrics = {
        "sample_count": len(rows),
        "session_count": len(set(groups)),
        "label_counts": dict(sorted(label_counts.items())),
        "session_counts_by_label": {
            label: len(sessions)
            for label, sessions in sorted(group_counts_by_label.items())
        },
        "cv_splits": n_splits,
    }
    if cv_predictions is not None:
        metrics["cv_accuracy"] = round(float(accuracy_score(labels, cv_predictions)), 4)
        metrics["cv_balanced_accuracy"] = round(
            float(balanced_accuracy_score(labels, cv_predictions)),
            4,
        )
    else:
        metrics["cv_accuracy"] = None
        metrics["cv_balanced_accuracy"] = None

    return {
        "schema_version": "left_hand_posture_model_report_v1",
        "model_name": "left_hand_posture_classifier",
        "model_type": "sklearn_random_forest",
        "model_path": str(model_output),
        "portable_model_path": str(portable_model_output),
        "feature_names": feature_names,
        "labels": sorted(label_counts),
        "metrics": metrics,
        "classification_report": cv_report,
        "confusion_matrix": cv_confusion,
        "training_notes": {
            "right_hand_ignored": True,
            "hand_identity_used_as_feature": False,
            "cross_validation_group": "session_id",
            "class_weight": class_weight,
            "normal_class_weight": normal_class_weight,
        },
    }


def export_portable_random_forest_model(model, output_path: Path) -> None:
    vectorizer = model.named_steps["features"]
    classifier = model.named_steps["classifier"]
    class_labels = [str(label) for label in classifier.classes_]
    trees = []

    for estimator in classifier.estimators_:
        tree = estimator.tree_
        trees.append(
            {
                "children_left": tree.children_left.tolist(),
                "children_right": tree.children_right.tolist(),
                "feature": tree.feature.tolist(),
                "threshold": tree.threshold.tolist(),
                "value": tree.value[:, 0, :].tolist(),
            }
        )

    payload = {
        "schema_version": "portable_random_forest_posture_model_v1",
        "model_name": "left_hand_posture_classifier",
        "model_version": output_path.stem,
        "feature_names": list(vectorizer.get_feature_names_out()),
        "classes": class_labels,
        "trees": trees,
    }
    write_json(output_path, payload)


if __name__ == "__main__":
    raise SystemExit(main())
