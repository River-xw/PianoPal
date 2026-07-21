from __future__ import annotations

import pytest

from backend.sensors import (
    HAND_SENSOR_PACKET_FIELD_COUNT,
    make_keystroke_windows,
    parse_hand_sensor_packet,
)


def test_parse_aggregate_hand_sensor_packet():
    line = "R,381,15230,120,-84,16320,3.2,-6.1,1.8,98,-70,16288,2.1,-4.4,1.2,110,-66,16310"

    packet = parse_hand_sensor_packet(line, received_at_unix_ms=1784563200123)

    assert packet is not None
    assert HAND_SENSOR_PACKET_FIELD_COUNT == 18
    assert packet.hand == "R"
    assert packet.sequence_number == 381
    assert packet.device_timestamp_ms == 15230
    assert packet.fingertip.accel.z == 16320
    assert packet.fingertip.gyro is not None
    assert packet.fingertip.gyro.y == -6.1
    assert packet.hand_back.gyro is not None
    assert packet.hand_back.gyro.x == 2.1
    assert packet.wrist.gyro is None
    assert packet.to_dict()["schema_version"] == "hand_imu_raw_v3"
    assert packet.to_dict()["sequence_number"] == 381
    assert packet.to_dict()["sensors"]["hand_back"]["accel"]["z"] == 16288
    assert packet.to_dict()["sensors"]["wrist"]["accel"]["z"] == 16310


def test_parse_invalid_packet_returns_none():
    assert parse_hand_sensor_packet("debug: connected", 1) is None
    assert parse_hand_sensor_packet("X,381,15230,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15", 1) is None
    assert parse_hand_sensor_packet("R,381,15230,1,2,not-a-number,4,5,6,7,8,9,10,11,12,13,14,15", 1) is None


def test_make_keystroke_windows_from_expected_and_played_times():
    expected = [0.0, 0.5, 1.0, 1.5, 2.0]
    played = [0.04, 0.43, 1.12, 1.68, 2.01]

    windows = make_keystroke_windows(expected, played)

    assert [w.offset_ms for w in windows] == [40.0, -70.0, 120.0, 180.0, 10.0]
    assert windows[0].window_start_sec == 0.0
    assert windows[0].window_end_sec == 0.34
    assert windows[2].window_start_sec == 0.62
    assert windows[2].window_end_sec == 1.42
    assert windows[4].window_start_sec == 1.51
    assert windows[4].window_end_sec == 2.31


def test_make_keystroke_windows_requires_equal_lengths():
    with pytest.raises(ValueError):
        make_keystroke_windows([0.0], [0.0, 0.5])
