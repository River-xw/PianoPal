"""Realtime IMU posture inference pipeline for Raspberry Pi."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from math import sqrt
from typing import Deque

from backend.sensors import RawHandSensorPacket


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

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        raise NotImplementedError


class ThresholdPostureModel(PostureModel):
    """Tiny placeholder until the trained Pi model is plugged in.

    This keeps the runtime path real: packets are windowed, features are
    extracted, a model-like object returns labels, and predictions are stored.
    Replace this class with an ONNX/TFLite/sklearn adapter after training.
    """

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        wrist_gyro = features.get("wrist_gyro_rms", 0.0)
        tip_gyro = features.get("fingertip_gyro_rms", 0.0)
        back_tilt = abs(features.get("hand_back_accel_mean_x", 0.0))

        if wrist_gyro >= 12.0:
            return "excessive_wrist_rotation", min(0.95, wrist_gyro / 30.0)
        if tip_gyro >= 12.0 and wrist_gyro < 4.0:
            return "isolated_finger_motion", min(0.9, tip_gyro / 30.0)
        if back_tilt >= 900.0:
            return "hand_back_tilt", min(0.9, back_tilt / 2000.0)
        return "normal", 0.6


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

        if len(buffer) < self.min_samples:
            return None

        features = extract_features(list(buffer))
        label, confidence = self.model.predict(features)
        return PosturePrediction(
            schema_version="imu_posture_prediction_v1",
            hand=packet.hand,
            sequence_number=packet.sequence_number,
            window_start_device_ms=buffer[0].device_timestamp_ms,
            window_end_device_ms=packet.device_timestamp_ms,
            sample_count=len(buffer),
            predicted_label=label,
            confidence=round(float(confidence), 4),
            model_name=self.model.model_name,
            model_version=self.model.model_version,
            features=features,
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
    back_x = [p.hand_back.accel.x for p in packets]
    back_y = [p.hand_back.accel.y for p in packets]
    back_z = [p.hand_back.accel.z for p in packets]

    fingertip_gyro = [
        _magnitude(p.fingertip.gyro.x, p.fingertip.gyro.y, p.fingertip.gyro.z)
        for p in packets
        if p.fingertip.gyro is not None
    ]
    wrist_gyro = [
        _magnitude(p.wrist.gyro.x, p.wrist.gyro.y, p.wrist.gyro.z)
        for p in packets
        if p.wrist.gyro is not None
    ]

    return {
        "fingertip_accel_rms": round(_rms(fingertip_accel), 4),
        "fingertip_gyro_rms": round(_rms(fingertip_gyro), 4),
        "wrist_accel_rms": round(_rms(wrist_accel), 4),
        "wrist_gyro_rms": round(_rms(wrist_gyro), 4),
        "hand_back_accel_mean_x": round(sum(back_x) / len(back_x), 4),
        "hand_back_accel_mean_y": round(sum(back_y) / len(back_y), 4),
        "hand_back_accel_mean_z": round(sum(back_z) / len(back_z), 4),
    }
