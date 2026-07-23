"""Realtime IMU posture inference pipeline for Raspberry Pi."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from math import sqrt
from pathlib import Path
from typing import Deque
import json

from backend.sensors import RawHandSensorPacket
from backend.sensors.training import extract_window_features


@dataclass(frozen=True)
class PosturePrediction:
    schema_version: str
    hand: str
    sequence_number: int
    window_start_device_ms: int
    window_end_device_ms: int
    sample_count: int
    predicted_label: str
    confidence: float
    model_name: str
    model_version: str
    features: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


class PostureModel:
    model_name = "imu_posture_classifier"
    model_version = "threshold_baseline_v0"
    feature_mode = "summary"

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        raise NotImplementedError


class ThresholdPostureModel(PostureModel):
    """Tiny placeholder until the trained Pi model is plugged in.

    This keeps the runtime path real: packets are windowed, features are
    extracted, a model-like object returns labels, and predictions are stored.
    Replace this class with an ONNX/TFLite/sklearn adapter after training.
    """

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        hand_back_gyro = features.get("hand_back_gyro_rms", 0.0)
        tip_gyro = features.get("fingertip_gyro_rms", 0.0)
        wrist_tilt = abs(features.get("wrist_accel_mean_x", 0.0))

        if hand_back_gyro >= 12.0:
            return "excessive_hand_rotation", min(0.95, hand_back_gyro / 30.0)
        if tip_gyro >= 12.0 and hand_back_gyro < 4.0:
            return "isolated_finger_motion", min(0.9, tip_gyro / 30.0)
        if wrist_tilt >= 900.0:
            return "wrist_tilt", min(0.9, wrist_tilt / 2000.0)
        return "normal", 0.6


class SklearnPostureModel(PostureModel):
    model_name = "left_hand_posture_classifier"
    feature_mode = "training_window"

    def __init__(self, model_path: str | Path) -> None:
        try:
            import joblib
        except ImportError as exc:
            raise RuntimeError(
                "Install joblib and scikit-learn on the Raspberry Pi to use --posture-model"
            ) from exc

        self.model_path = Path(model_path)
        self.model = joblib.load(self.model_path)
        self.model_version = self.model_path.stem

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        predicted_label = str(self.model.predict([features])[0])
        confidence = 1.0
        if hasattr(self.model, "predict_proba"):
            probabilities = self.model.predict_proba([features])[0]
            class_labels = [str(label) for label in self.model.classes_]
            confidence = float(probabilities[class_labels.index(predicted_label)])
        return predicted_label, confidence


class PortableRandomForestPostureModel(PostureModel):
    feature_mode = "training_window"

    def __init__(self, model_path: str | Path) -> None:
        self.model_path = Path(model_path)
        data = json.loads(self.model_path.read_text(encoding="utf-8"))
        if data.get("schema_version") != "portable_random_forest_posture_model_v1":
            raise ValueError("unsupported portable posture model JSON")
        self.model_name = str(data.get("model_name", "left_hand_posture_classifier"))
        self.model_version = str(data.get("model_version", self.model_path.stem))
        self.feature_names = [str(name) for name in data["feature_names"]]
        self.classes = [str(label) for label in data["classes"]]
        self.trees = data["trees"]

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        vector = [float(features.get(name, 0.0)) for name in self.feature_names]
        probabilities = [0.0] * len(self.classes)

        for tree in self.trees:
            leaf_values = _portable_tree_leaf_values(tree, vector)
            total = sum(float(value) for value in leaf_values)
            if total <= 0.0:
                continue
            for index, value in enumerate(leaf_values):
                probabilities[index] += float(value) / total

        if not self.trees:
            raise ValueError("portable posture model contains no trees")

        probabilities = [value / len(self.trees) for value in probabilities]
        best_index = max(range(len(probabilities)), key=lambda index: probabilities[index])
        return self.classes[best_index], probabilities[best_index]


class RealtimePosturePipeline:
    def __init__(
        self,
        model: PostureModel | None = None,
        window_ms: int = 800,
        min_samples: int = 4,
    ) -> None:
        self.model = model or ThresholdPostureModel()
        self.window_ms = window_ms
        self.min_samples = min_samples
        self.buffers: dict[str, Deque[RawHandSensorPacket]] = {
            "L": deque(),
            "R": deque(),
        }

    def add_packet(self, packet: RawHandSensorPacket) -> PosturePrediction | None:
        buffer = self.buffers[packet.hand]
        buffer.append(packet)
        cutoff = packet.device_timestamp_ms - self.window_ms

        while buffer and buffer[0].device_timestamp_ms < cutoff:
            buffer.popleft()

        valid_packets = [
            item
            for item in buffer
            if _packet_has_required_sensor_data(item)
            and not _packet_has_saturated_external_mpu_value(item)
        ]
        if len(valid_packets) < self.min_samples:
            return None

        if self.model.feature_mode == "training_window":
            features = extract_window_features(list(valid_packets), prefix="")
        else:
            features = extract_features(list(valid_packets))
        label, confidence = self.model.predict(features)
        return PosturePrediction(
            schema_version="imu_posture_prediction_v1",
            hand=packet.hand,
            sequence_number=packet.sequence_number,
            window_start_device_ms=valid_packets[0].device_timestamp_ms,
            window_end_device_ms=packet.device_timestamp_ms,
            sample_count=len(valid_packets),
            predicted_label=label,
            confidence=round(float(confidence), 4),
            model_name=self.model.model_name,
            model_version=self.model.model_version,
            features=features,
        )


def load_posture_model(model_path: str | Path | None) -> PostureModel:
    if model_path is None:
        return ThresholdPostureModel()
    path = Path(model_path)
    if path.suffix.lower() == ".json":
        return PortableRandomForestPostureModel(path)
    return SklearnPostureModel(path)


def _portable_tree_leaf_values(tree: dict, vector: list[float]) -> list[float]:
    node = 0
    while True:
        left = int(tree["children_left"][node])
        right = int(tree["children_right"][node])
        if left == right or left < 0:
            return tree["value"][node]
        feature_index = int(tree["feature"][node])
        threshold = float(tree["threshold"][node])
        node = left if vector[feature_index] <= threshold else right


def _packet_has_required_sensor_data(packet: RawHandSensorPacket) -> bool:
    return all(
        not _reading_is_all_zero(reading)
        for reading in (packet.fingertip, packet.hand_back, packet.wrist)
    )


def _reading_is_all_zero(reading) -> bool:
    vectors = [reading.accel]
    if reading.gyro is not None:
        vectors.append(reading.gyro)
    return all(
        vector.x == 0.0 and vector.y == 0.0 and vector.z == 0.0
        for vector in vectors
    )


def _packet_has_saturated_external_mpu_value(packet: RawHandSensorPacket) -> bool:
    return any(
        abs(float(value)) >= 32760.0
        for reading in (packet.fingertip, packet.hand_back)
        for vector in (reading.accel, reading.gyro)
        if vector is not None
        for value in (vector.x, vector.y, vector.z)
    )


def _rms(values: list[float]) -> float:
    if not values:
        return 0.0
    return sqrt(sum(value * value for value in values) / len(values))


def _magnitude(x: float, y: float, z: float) -> float:
    return sqrt(x * x + y * y + z * z)


def extract_features(packets: list[RawHandSensorPacket]) -> dict[str, float]:
    fingertip_accel = [
        _magnitude(p.fingertip.accel.x, p.fingertip.accel.y, p.fingertip.accel.z)
        for p in packets
    ]
    wrist_accel = [
        _magnitude(p.wrist.accel.x, p.wrist.accel.y, p.wrist.accel.z)
        for p in packets
    ]
    wrist_x = [p.wrist.accel.x for p in packets]
    wrist_y = [p.wrist.accel.y for p in packets]
    wrist_z = [p.wrist.accel.z for p in packets]
    hand_back_accel = [
        _magnitude(p.hand_back.accel.x, p.hand_back.accel.y, p.hand_back.accel.z)
        for p in packets
    ]

    fingertip_gyro = [
        _magnitude(p.fingertip.gyro.x, p.fingertip.gyro.y, p.fingertip.gyro.z)
        for p in packets
        if p.fingertip.gyro is not None
    ]
    hand_back_gyro = [
        _magnitude(p.hand_back.gyro.x, p.hand_back.gyro.y, p.hand_back.gyro.z)
        for p in packets
        if p.hand_back.gyro is not None
    ]

    return {
        "fingertip_accel_rms": round(_rms(fingertip_accel), 4),
        "fingertip_gyro_rms": round(_rms(fingertip_gyro), 4),
        "hand_back_accel_rms": round(_rms(hand_back_accel), 4),
        "hand_back_gyro_rms": round(_rms(hand_back_gyro), 4),
        "wrist_accel_rms": round(_rms(wrist_accel), 4),
        "wrist_accel_mean_x": round(sum(wrist_x) / len(wrist_x), 4),
        "wrist_accel_mean_y": round(sum(wrist_y) / len(wrist_y), 4),
        "wrist_accel_mean_z": round(sum(wrist_z) / len(wrist_z), 4),
    }
