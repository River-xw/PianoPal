"""Training-data helpers for audio-triggered IMU keypress windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable
import json

from .schemas import RawHandSensorPacket, SensorReading, SensorVector


SENSOR_NAMES = ("fingertip", "hand_back", "wrist")
READING_NAMES = ("accel", "gyro")
AXES = ("x", "y", "z")


@dataclass(frozen=True)
class OnsetEvent:
    event_index: int
    onset_sec: float
    pitches: list[int]
    velocities: list[int]


def load_performance_json(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("notes"), list):
        data = data["notes"]
    if not isinstance(data, list):
        raise ValueError("performance JSON must be a list of notes or an object with a notes list")
    return data


def performance_to_onset_events(
    notes: Iterable[dict[str, Any]],
    merge_sec: float = 0.03,
) -> list[OnsetEvent]:
    """Collapse note onsets into physical keypress/chord events."""

    sorted_notes = sorted(notes, key=lambda note: (float(note["onset_sec"]), int(note["pitch"])))
    events: list[OnsetEvent] = []
    current: list[dict[str, Any]] = []
    current_start: float | None = None

    for note in sorted_notes:
        onset = float(note["onset_sec"])
        if current and current_start is not None and onset - current_start > merge_sec:
            events.append(_make_onset_event(len(events), current))
            current = []
            current_start = None

        if not current:
            current_start = onset
        current.append(note)

    if current:
        events.append(_make_onset_event(len(events), current))

    return events


def load_hand_packets(path: str | Path) -> list[RawHandSensorPacket]:
    packets = []
    with Path(path).open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                packets.append(hand_packet_from_dict(json.loads(line)))
            except Exception as exc:
                raise ValueError(f"invalid IMU JSONL at {path}:{line_number}: {exc}") from exc
    return packets


def hand_packet_from_dict(data: dict[str, Any]) -> RawHandSensorPacket:
    sensors = data["sensors"]
    return RawHandSensorPacket(
        hand=data["hand"],
        sequence_number=int(data["sequence_number"]),
        device_timestamp_ms=int(data["device_timestamp_ms"]),
        received_at_unix_ms=int(data["received_at_unix_ms"]),
        fingertip=_reading_from_dict(sensors["fingertip"]),
        wrist=_reading_from_dict(sensors["wrist"]),
        hand_back=_reading_from_dict(sensors["hand_back"]),
        schema_version=data.get("schema_version", "hand_imu_raw_v3"),
    )


def load_event_labels(path: str | Path, event_count: int) -> list[str]:
    """Load labels from a flexible JSON shape.

    Accepted examples:
    - ["normal", "wrist_drop"]
    - {"labels": ["normal", "wrist_drop"]}
    - {"0": "normal", "1": "wrist_drop"}
    - [{"event_index": 0, "label": "normal"}]
    """

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    labels: list[str | None] = [None] * event_count

    if isinstance(data, dict) and isinstance(data.get("labels"), list):
        data = data["labels"]

    if isinstance(data, list):
        if all(isinstance(item, str) for item in data):
            for index, label in enumerate(data[:event_count]):
                labels[index] = label
        elif all(isinstance(item, dict) for item in data):
            for item in data:
                index = int(item.get("event_index", item.get("onset_index", item.get("index"))))
                if 0 <= index < event_count:
                    labels[index] = str(item["label"])
        else:
            raise ValueError("label list must contain only strings or only objects")
    elif isinstance(data, dict):
        for key, value in data.items():
            index = int(key)
            if 0 <= index < event_count:
                labels[index] = str(value)
    else:
        raise ValueError("labels JSON must be a list or object")

    missing = [index for index, label in enumerate(labels) if label is None]
    if missing:
        raise ValueError(f"missing labels for event indexes: {missing[:10]}")
    return [str(label) for label in labels]


def build_feature_rows(
    *,
    session_id: str,
    performance_notes: list[dict[str, Any]],
    left_packets: list[RawHandSensorPacket],
    right_packets: list[RawHandSensorPacket],
    labels: list[str],
    pre_sec: float = 0.5,
    post_sec: float = 0.3,
    onset_merge_sec: float = 0.03,
    imu_time_offset_sec: float = 0.0,
) -> list[dict[str, Any]]:
    events = performance_to_onset_events(performance_notes, onset_merge_sec)
    if len(labels) != len(events):
        raise ValueError(f"label count ({len(labels)}) does not match event count ({len(events)})")

    streams = {"L": left_packets, "R": right_packets}
    base_ms = {
        hand: packets[0].device_timestamp_ms if packets else 0
        for hand, packets in streams.items()
    }
    rows = []

    for event, label in zip(events, labels):
        feature_map: dict[str, float] = {}
        sample_counts: dict[str, int] = {}

        window_start_sec = max(0.0, event.onset_sec - pre_sec)
        window_end_sec = event.onset_sec + post_sec

        for hand, packets in streams.items():
            start_ms = base_ms[hand] + int(round((window_start_sec + imu_time_offset_sec) * 1000.0))
            end_ms = base_ms[hand] + int(round((window_end_sec + imu_time_offset_sec) * 1000.0))
            window_packets = [
                packet for packet in packets
                if start_ms <= packet.device_timestamp_ms <= end_ms
            ]
            sample_counts[hand] = len(window_packets)
            feature_map.update(extract_window_features(window_packets, prefix=hand))

        rows.append(
            {
                "schema_version": "imu_keypress_feature_window_v1",
                "session_id": session_id,
                "event_index": event.event_index,
                "onset_sec": round(event.onset_sec, 6),
                "window_start_sec": round(window_start_sec, 6),
                "window_end_sec": round(window_end_sec, 6),
                "pitches": event.pitches,
                "velocities": event.velocities,
                "label": label,
                "sample_counts": sample_counts,
                "features": feature_map,
            }
        )

    return rows


def extract_window_features(
    packets: list[RawHandSensorPacket],
    prefix: str,
) -> dict[str, float]:
    features: dict[str, float] = {}
    if not packets:
        return features

    for sensor_name in SENSOR_NAMES:
        for reading_name in READING_NAMES:
            vectors = [
                getattr(getattr(packet, sensor_name), reading_name)
                for packet in packets
            ]
            vectors = [vector for vector in vectors if vector is not None]
            if not vectors:
                continue

            for axis in AXES:
                values = [float(getattr(vector, axis)) for vector in vectors]
                features.update(_series_features(f"{prefix}_{sensor_name}_{reading_name}_{axis}", values))

            magnitudes = [
                sqrt(vector.x * vector.x + vector.y * vector.y + vector.z * vector.z)
                for vector in vectors
            ]
            features.update(_series_features(f"{prefix}_{sensor_name}_{reading_name}_mag", magnitudes))

    if len(packets) >= 2:
        duration_sec = (packets[-1].device_timestamp_ms - packets[0].device_timestamp_ms) / 1000.0
        features[f"{prefix}_window_duration_sec"] = round(max(0.0, duration_sec), 6)
    features[f"{prefix}_sample_count"] = float(len(packets))
    return features


def train_nearest_centroid_model(
    rows: list[dict[str, Any]],
    *,
    model_name: str = "hand_imu_keypress_classifier",
    model_version: str | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("at least one feature row is required")

    feature_names = sorted({
        feature_name
        for row in rows
        for feature_name in row["features"].keys()
    })
    if not feature_names:
        raise ValueError("feature rows do not contain any IMU features")

    labels = sorted({str(row["label"]) for row in rows})
    vectors = [_row_vector(row, feature_names) for row in rows]
    centroids = {}
    priors = {}

    for label in labels:
        label_vectors = [vector for row, vector in zip(rows, vectors) if row["label"] == label]
        priors[label] = len(label_vectors) / len(vectors)
        centroids[label] = [
            round(mean(values), 8)
            for values in zip(*label_vectors)
        ]

    predictions = [
        predict_nearest_centroid(vector, centroids)
        for vector in vectors
    ]
    correct = sum(1 for row, prediction in zip(rows, predictions) if row["label"] == prediction)

    return {
        "schema_version": "imu_nearest_centroid_model_v1",
        "model_name": model_name,
        "model_version": model_version or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "classifier": "nearest_centroid",
        "feature_names": feature_names,
        "labels": labels,
        "centroids": centroids,
        "priors": priors,
        "feature_fill_value": 0.0,
        "metrics": {
            "training_samples": len(rows),
            "training_accuracy": round(correct / len(rows), 4),
        },
    }


def predict_nearest_centroid(vector: list[float], centroids: dict[str, list[float]]) -> str:
    best_label = None
    best_distance = None
    for label, centroid in centroids.items():
        distance = sum((value - center) ** 2 for value, center in zip(vector, centroid))
        if best_distance is None or distance < best_distance:
            best_label = label
            best_distance = distance
    if best_label is None:
        raise ValueError("model has no centroids")
    return best_label


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _make_onset_event(event_index: int, notes: list[dict[str, Any]]) -> OnsetEvent:
    return OnsetEvent(
        event_index=event_index,
        onset_sec=min(float(note["onset_sec"]) for note in notes),
        pitches=[int(note["pitch"]) for note in notes],
        velocities=[int(note.get("velocity", 0)) for note in notes],
    )


def _reading_from_dict(data: dict[str, Any]) -> SensorReading:
    gyro = data.get("gyro")
    return SensorReading(
        accel=_vector_from_dict(data["accel"]),
        gyro=_vector_from_dict(gyro) if gyro is not None else None,
    )


def _vector_from_dict(data: dict[str, Any]) -> SensorVector:
    return SensorVector(float(data["x"]), float(data["y"]), float(data["z"]))


def _series_features(name: str, values: list[float]) -> dict[str, float]:
    first = values[0]
    last = values[-1]
    return {
        f"{name}_mean": round(mean(values), 6),
        f"{name}_std": round(pstdev(values), 6) if len(values) > 1 else 0.0,
        f"{name}_min": round(min(values), 6),
        f"{name}_max": round(max(values), 6),
        f"{name}_range": round(max(values) - min(values), 6),
        f"{name}_rms": round(sqrt(sum(value * value for value in values) / len(values)), 6),
        f"{name}_delta": round(last - first, 6),
    }


def _row_vector(row: dict[str, Any], feature_names: list[str]) -> list[float]:
    features = row["features"]
    return [float(features.get(feature_name, 0.0)) for feature_name in feature_names]
