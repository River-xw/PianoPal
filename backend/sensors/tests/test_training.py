from __future__ import annotations

import json

from backend.sensors import RawHandSensorPacket, SensorReading, SensorVector
from backend.sensors.training import (
    build_feature_rows,
    load_event_labels,
    load_hand_packets,
    load_performance_json,
    performance_to_onset_events,
    train_nearest_centroid_model,
)


def test_performance_to_onset_events_merges_chords():
    notes = [
        {"pitch": 60, "onset_sec": 1.0, "dur_sec": 0.2, "velocity": 80},
        {"pitch": 64, "onset_sec": 1.02, "dur_sec": 0.2, "velocity": 70},
        {"pitch": 67, "onset_sec": 1.2, "dur_sec": 0.2, "velocity": 90},
    ]

    events = performance_to_onset_events(notes, merge_sec=0.03)

    assert len(events) == 2
    assert events[0].onset_sec == 1.0
    assert events[0].pitches == [60, 64]
    assert events[1].pitches == [67]


def test_build_feature_rows_uses_all_hand_sensors():
    performance = [
        {"pitch": 60, "onset_sec": 0.5, "dur_sec": 0.2, "velocity": 80},
        {"pitch": 62, "onset_sec": 1.5, "dur_sec": 0.2, "velocity": 80},
    ]
    left = [_packet("L", index, timestamp_ms, base=10.0) for index, timestamp_ms in enumerate(range(0, 2100, 100))]
    right = [_packet("R", index, timestamp_ms, base=30.0) for index, timestamp_ms in enumerate(range(0, 2100, 100))]

    rows = build_feature_rows(
        session_id="sess_test",
        performance_notes=performance,
        left_packets=left,
        right_packets=right,
        labels=["normal", "raised_finger"],
        pre_sec=0.2,
        post_sec=0.2,
    )

    assert len(rows) == 2
    assert rows[0]["sample_counts"] == {"L": 5, "R": 5}
    features = rows[0]["features"]
    assert "L_fingertip_accel_x_mean" in features
    assert "L_hand_back_gyro_z_rms" in features
    assert "R_wrist_accel_mag_max" in features

    model = train_nearest_centroid_model(rows)
    assert model["classifier"] == "nearest_centroid"
    assert model["metrics"]["training_samples"] == 2
    assert set(model["labels"]) == {"normal", "raised_finger"}


def test_load_packets_and_labels(tmp_path):
    packet_path = tmp_path / "imu.jsonl"
    packet = _packet("R", 1, 100, base=2.0)
    packet_path.write_text(json.dumps(packet.to_dict()) + "\n", encoding="utf-8")
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps({"labels": ["normal"]}), encoding="utf-8")

    packets = load_hand_packets(packet_path)
    labels = load_event_labels(labels_path, event_count=1)

    assert packets[0].hand == "R"
    assert packets[0].hand_back.gyro is not None
    assert labels == ["normal"]


def test_load_performance_json_accepts_plain_or_wrapped_notes(tmp_path):
    notes = [{"pitch": 60, "onset_sec": 0.5, "dur_sec": 0.2, "velocity": 80}]
    plain_path = tmp_path / "plain.json"
    wrapped_path = tmp_path / "wrapped.json"
    plain_path.write_text(json.dumps(notes), encoding="utf-8")
    wrapped_path.write_text(json.dumps({"notes": notes}), encoding="utf-8")

    assert load_performance_json(plain_path) == notes
    assert load_performance_json(wrapped_path) == notes


def _packet(hand: str, seq: int, timestamp_ms: int, base: float) -> RawHandSensorPacket:
    value = base + seq
    return RawHandSensorPacket(
        hand=hand,  # type: ignore[arg-type]
        sequence_number=seq,
        device_timestamp_ms=timestamp_ms,
        received_at_unix_ms=1784563200000 + timestamp_ms,
        fingertip=SensorReading(
            accel=SensorVector(value, value + 1, value + 2),
            gyro=SensorVector(value + 3, value + 4, value + 5),
        ),
        hand_back=SensorReading(
            accel=SensorVector(value + 6, value + 7, value + 8),
            gyro=SensorVector(value + 9, value + 10, value + 11),
        ),
        wrist=SensorReading(
            accel=SensorVector(value + 12, value + 13, value + 14),
            gyro=None,
        ),
    )
