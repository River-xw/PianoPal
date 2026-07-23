from __future__ import annotations

import json

from backend.sensors import RawHandSensorPacket, SensorReading, SensorVector
from backend.sensors.training import (
    build_feature_rows,
    load_audio_start_unix_ms,
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


def test_build_feature_rows_pools_hands_with_shared_feature_names():
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

    assert len(rows) == 4
    assert [row["hand"] for row in rows] == ["L", "R", "L", "R"]
    assert rows[0]["sample_count"] == 5
    features = rows[0]["features"]
    assert "fingertip_accel_x_mean" in features
    assert "hand_back_gyro_z_rms" in features
    assert "wrist_accel_mag_max" in features
    assert not any(name.startswith(("L_", "R_")) for name in features)
    assert rows[0]["time_alignment"]["hand"]["method"] == "legacy_first_packet"

    model = train_nearest_centroid_model(rows)
    assert model["classifier"] == "nearest_centroid"
    assert model["metrics"]["training_samples"] == 4
    assert not any(name.startswith(("L_", "R_")) for name in model["feature_names"])
    assert set(model["labels"]) == {"normal", "raised_finger"}


def test_load_packets_and_labels(tmp_path):
    packet_path = tmp_path / "imu.jsonl"
    packet = _packet("R", 1, 100, base=2.0)
    packet_path.write_text(json.dumps(packet.to_dict()) + "\n", encoding="utf-8")
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps({"labels": ["normal"]}), encoding="utf-8")
    timing_path = tmp_path / "timing.json"
    timing_path.write_text(
        json.dumps({"audio": {"started_at_unix_ms": 1784563200000}}),
        encoding="utf-8",
    )

    packets = load_hand_packets(packet_path)
    labels = load_event_labels(labels_path, event_count=1)

    assert packets[0].hand == "R"
    assert packets[0].hand_back.gyro is not None
    assert labels == ["normal"]
    assert load_audio_start_unix_ms(timing_path) == 1784563200000


def test_build_feature_rows_aligns_device_clock_to_audio_start():
    audio_started_at_unix_ms = 1784563200000
    performance = [
        {"pitch": 60, "onset_sec": 1.0, "dur_sec": 0.2, "velocity": 80},
    ]
    left = [
        _packet("L", index, timestamp_ms, base=10.0, receive_delay_ms=500)
        for index, timestamp_ms in enumerate(range(0, 2100, 100))
    ]
    right = [
        _packet("R", index, timestamp_ms, base=30.0, receive_delay_ms=500)
        for index, timestamp_ms in enumerate(range(0, 2100, 100))
    ]

    rows = build_feature_rows(
        session_id="sess_synced",
        performance_notes=performance,
        left_packets=left,
        right_packets=right,
        labels=["normal"],
        pre_sec=0.2,
        post_sec=0.2,
        audio_started_at_unix_ms=audio_started_at_unix_ms,
    )

    assert len(rows) == 2
    assert rows[0]["hand"] == "L"
    assert rows[0]["sample_count"] == 5
    assert rows[0]["features"]["fingertip_accel_x_mean"] == 15.0
    alignment = rows[0]["time_alignment"]["hand"]
    assert alignment["method"] == "median_received_minus_device_timestamp"
    assert alignment["device_to_unix_offset_ms"] == 1784563200500.0


def test_build_feature_rows_drops_only_the_hand_with_zero_sensor_data():
    performance = [
        {"pitch": 60, "onset_sec": 1.0, "dur_sec": 0.2, "velocity": 80},
    ]
    left = [
        _packet(
            "L",
            index,
            timestamp_ms,
            base=10.0,
            zero_hand_back=timestamp_ms in {800, 900},
        )
        for index, timestamp_ms in enumerate(range(0, 2100, 100))
    ]
    right = [
        _packet("R", index, timestamp_ms, base=30.0)
        for index, timestamp_ms in enumerate(range(0, 2100, 100))
    ]

    rows = build_feature_rows(
        session_id="sess_quality",
        performance_notes=performance,
        left_packets=left,
        right_packets=right,
        labels=["normal"],
        pre_sec=0.2,
        post_sec=0.2,
    )

    assert len(rows) == 2
    left_row, right_row = rows
    assert left_row["hand"] == "L"
    assert left_row["raw_sample_count"] == 5
    assert left_row["sample_count"] == 3
    assert left_row["invalid_sample_count"] == 2
    assert left_row["valid_ratio"] == 0.6
    assert left_row["usable_for_training"] is False
    assert "valid_ratio_below_0.8" in left_row["quality_reasons"]
    assert right_row["hand"] == "R"
    assert right_row["usable_for_training"] is True

    model = train_nearest_centroid_model(rows)
    assert model["metrics"]["input_samples"] == 2
    assert model["metrics"]["training_samples"] == 1
    assert model["metrics"]["dropped_samples"] == 1
    assert model["labels"] == ["normal"]


def test_audio_alignment_handles_device_timestamp_reset_after_reconnect():
    audio_started_at_unix_ms = 1784563200000
    first_segment = [
        _packet("L", index, timestamp_ms, base=10.0)
        for index, timestamp_ms in enumerate(range(0, 500, 100))
    ]
    second_segment = [
        _packet(
            "L",
            index,
            timestamp_ms,
            base=10.0,
            receive_delay_ms=1000,
        )
        for index, timestamp_ms in enumerate(range(0, 500, 100))
    ]
    right = [
        _packet("R", index, timestamp_ms, base=30.0)
        for index, timestamp_ms in enumerate(range(0, 1500, 100))
    ]
    performance = [
        {"pitch": 60, "onset_sec": 0.2, "dur_sec": 0.1, "velocity": 80},
        {"pitch": 62, "onset_sec": 1.2, "dur_sec": 0.1, "velocity": 80},
    ]

    rows = build_feature_rows(
        session_id="sess_reconnect",
        performance_notes=performance,
        left_packets=first_segment + second_segment,
        right_packets=right,
        labels=["normal", "normal"],
        pre_sec=0.05,
        post_sec=0.05,
        audio_started_at_unix_ms=audio_started_at_unix_ms,
        min_valid_samples_per_hand=1,
    )

    alignment = rows[0]["time_alignment"]["hand"]
    assert alignment["segment_count"] == 2
    assert rows[0]["hand"] == "L"
    assert rows[0]["sample_count"] == 1
    assert rows[2]["hand"] == "L"
    assert rows[2]["sample_count"] == 1


def test_load_performance_json_accepts_plain_or_wrapped_notes(tmp_path):
    notes = [{"pitch": 60, "onset_sec": 0.5, "dur_sec": 0.2, "velocity": 80}]
    plain_path = tmp_path / "plain.json"
    wrapped_path = tmp_path / "wrapped.json"
    plain_path.write_text(json.dumps(notes), encoding="utf-8")
    wrapped_path.write_text(json.dumps({"notes": notes}), encoding="utf-8")

    assert load_performance_json(plain_path) == notes
    assert load_performance_json(wrapped_path) == notes


def _packet(
    hand: str,
    seq: int,
    timestamp_ms: int,
    base: float,
    receive_delay_ms: int = 0,
    zero_hand_back: bool = False,
) -> RawHandSensorPacket:
    value = base + seq
    hand_back = (
        SensorReading(
            accel=SensorVector(0.0, 0.0, 0.0),
            gyro=SensorVector(0.0, 0.0, 0.0),
        )
        if zero_hand_back
        else SensorReading(
            accel=SensorVector(value + 6, value + 7, value + 8),
            gyro=SensorVector(value + 9, value + 10, value + 11),
        )
    )
    return RawHandSensorPacket(
        hand=hand,  # type: ignore[arg-type]
        sequence_number=seq,
        device_timestamp_ms=timestamp_ms,
        received_at_unix_ms=1784563200000 + receive_delay_ms + timestamp_ms,
        fingertip=SensorReading(
            accel=SensorVector(value, value + 1, value + 2),
            gyro=SensorVector(value + 3, value + 4, value + 5),
        ),
        hand_back=hand_back,
        wrist=SensorReading(
            accel=SensorVector(value + 12, value + 13, value + 14),
            gyro=None,
        ),
    )
