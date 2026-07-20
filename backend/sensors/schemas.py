"""Schemas for PianoPal's hand IMU acquisition data.

The Raspberry Pi collection script should keep raw streams as JSONL files.
Each line is one normalized ``RawHandSensorPacket``. SQLite only stores the
artifact paths; ChromaDB stores derived feature windows and labels.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


Hand = Literal["L", "R"]
SensorPosition = Literal["fingertip", "wrist", "hand_back"]

# One hand per line:
# hand,seq,timestamp_ms,
# fingertip ax,ay,az,gx,gy,gz,
# wrist ax,ay,az,gx,gy,gz,
# hand_back ax,ay,az
HAND_SENSOR_PACKET_FIELD_COUNT = 18


@dataclass(frozen=True)
class SensorVector:
    x: float
    y: float
    z: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class SensorReading:
    accel: SensorVector
    gyro: SensorVector | None = None

    def to_dict(self) -> dict:
        return {
            "accel": self.accel.to_dict(),
            "gyro": self.gyro.to_dict() if self.gyro is not None else None,
        }


@dataclass(frozen=True)
class RawHandSensorPacket:
    """One normalized packet received from a hand-mounted micro:bit."""

    hand: Hand
    sequence_number: int
    device_timestamp_ms: int
    received_at_unix_ms: int
    fingertip: SensorReading
    wrist: SensorReading
    hand_back: SensorReading
    schema_version: str = "hand_imu_raw_v2"

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "hand": self.hand,
            "sequence_number": self.sequence_number,
            "device_timestamp_ms": self.device_timestamp_ms,
            "received_at_unix_ms": self.received_at_unix_ms,
            "sensors": {
                "fingertip": self.fingertip.to_dict(),
                "wrist": self.wrist.to_dict(),
                "hand_back": self.hand_back.to_dict(),
            },
        }


@dataclass(frozen=True)
class KeypressWindow:
    """A sensor collection window aligned to one detected note onset."""

    ref_index: int
    expected_onset_sec: float
    played_onset_sec: float
    offset_ms: float
    window_start_sec: float
    window_end_sec: float
    schema_version: str = "keypress_window_v1"

    def to_dict(self) -> dict:
        return asdict(self)


def parse_hand_sensor_packet(
    line: str,
    received_at_unix_ms: int,
) -> RawHandSensorPacket | None:
    """Parse one fixed-format CSV packet from a hand micro:bit.

    Expected packet:

        R,seq,timestamp,tip_ax,tip_ay,tip_az,tip_gx,tip_gy,tip_gz,
        wrist_ax,wrist_ay,wrist_az,wrist_gx,wrist_gy,wrist_gz,
        back_ax,back_ay,back_az

    Invalid packets return ``None`` so the Raspberry Pi reader can skip them.
    """

    parts = [part.strip() for part in line.strip().split(",")]
    if len(parts) != HAND_SENSOR_PACKET_FIELD_COUNT:
        return None

    hand = parts[0].upper()
    if hand not in {"L", "R"}:
        return None

    try:
        sequence_number = int(parts[1])
        timestamp_ms = int(parts[2])
        values = [float(value) for value in parts[3:]]
    except ValueError:
        return None

    fingertip = SensorReading(
        accel=SensorVector(values[0], values[1], values[2]),
        gyro=SensorVector(values[3], values[4], values[5]),
    )
    wrist = SensorReading(
        accel=SensorVector(values[6], values[7], values[8]),
        gyro=SensorVector(values[9], values[10], values[11]),
    )
    hand_back = SensorReading(
        accel=SensorVector(values[12], values[13], values[14]),
        gyro=None,
    )

    return RawHandSensorPacket(
        hand=hand,  # type: ignore[arg-type]
        sequence_number=sequence_number,
        device_timestamp_ms=timestamp_ms,
        received_at_unix_ms=received_at_unix_ms,
        fingertip=fingertip,
        wrist=wrist,
        hand_back=hand_back,
    )


def make_keystroke_windows(
    expected_onsets_sec: list[float],
    played_onsets_sec: list[float],
    pre_sec: float = 0.5,
    post_sec: float = 0.3,
) -> list[KeypressWindow]:
    """Build per-note IMU collection windows from expected and played onsets.

    The window is anchored to the microphone/audio-detected played onset:
    ``played_onset_sec - pre_sec`` to ``played_onset_sec + post_sec``.
    """

    if len(expected_onsets_sec) != len(played_onsets_sec):
        raise ValueError("expected_onsets_sec and played_onsets_sec must have equal length")

    windows = []
    for index, (expected, played) in enumerate(zip(expected_onsets_sec, played_onsets_sec)):
        windows.append(
            KeypressWindow(
                ref_index=index,
                expected_onset_sec=expected,
                played_onset_sec=played,
                offset_ms=round((played - expected) * 1000.0, 3),
                window_start_sec=max(0.0, round(played - pre_sec, 6)),
                window_end_sec=round(played + post_sec, 6),
            )
        )

    return windows
