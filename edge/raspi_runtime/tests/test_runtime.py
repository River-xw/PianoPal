from __future__ import annotations

import json
import pytest

from backend.db import get_recent_sessions, get_session_artifacts
from backend.sensors import RawHandSensorPacket, SensorReading, SensorVector
from edge.raspi_runtime.audio import AudioStartTiming
import edge.raspi_runtime.session as session_module
from edge.raspi_runtime.session import RuntimeConfig, run_session


def test_simulated_runtime_writes_session_files(tmp_path):
    import asyncio

    config = RuntimeConfig(
        user_id="u_test",
        user_name="Test",
        piece_id="piece_test",
        piece_title="Test Piece",
        piece_composer=None,
        session_id="sess_test",
        data_root=tmp_path / "data",
        mode="simulate",
        ble_config=None,
        duration_sec=0.45,
        target_bpm=80,
        db_path=tmp_path / "pianopal.sqlite3",
    )

    paths = asyncio.run(run_session(config))

    assert paths.imu_left_path.exists()
    assert paths.imu_right_path.exists()
    assert paths.imu_predictions_path.exists()
    assert paths.audio_path.exists()
    assert paths.timing_path.exists()

    left_lines = paths.imu_left_path.read_text(encoding="utf-8").splitlines()
    prediction_lines = paths.imu_predictions_path.read_text(encoding="utf-8").splitlines()

    assert left_lines
    assert json.loads(left_lines[0])["schema_version"] == "hand_imu_raw_v3"
    assert prediction_lines
    assert json.loads(prediction_lines[0])["schema_version"] == "imu_posture_prediction_v1"

    timing = json.loads(paths.timing_path.read_text(encoding="utf-8"))
    assert timing["schema_version"] == "audio_imu_timing_v1"
    assert timing["audio"]["started_at_unix_ms"] > 0
    assert timing["audio"]["stopped_at_unix_ms"] >= timing["audio"]["started_at_unix_ms"]
    assert timing["imu"]["alignment_method"] == "median_received_minus_device_timestamp"
    assert timing["imu"]["hands"]["L"]["first_received_at_unix_ms"] > 0

    sessions = get_recent_sessions("u_test", db_path=config.db_path)
    artifacts = get_session_artifacts("sess_test", db_path=config.db_path)

    assert sessions[0]["status"] == "acquired"
    assert sessions[0]["summary_json"] is not None
    assert {artifact["artifact_type"] for artifact in artifacts} == {
        "raw_audio",
        "acquisition_timing",
        "imu_left_raw",
        "imu_right_raw",
        "imu_predictions",
    }


def test_audio_only_runtime_records_audio_artifact(tmp_path):
    import asyncio

    config = RuntimeConfig(
        user_id="u_audio",
        user_name="Audio",
        piece_id="piece_audio",
        piece_title="Audio Test",
        piece_composer=None,
        session_id="sess_audio",
        data_root=tmp_path / "data",
        mode="audio-only",
        ble_config=None,
        duration_sec=0.01,
        target_bpm=None,
        db_path=tmp_path / "pianopal.sqlite3",
    )

    paths = asyncio.run(run_session(config))

    assert paths.audio_path.exists()
    assert paths.timing_path.exists()
    assert paths.audio_path.read_text(encoding="utf-8")
    assert not paths.imu_left_path.exists()
    assert not paths.imu_right_path.exists()
    assert not paths.imu_predictions_path.exists()

    sessions = get_recent_sessions("u_audio", db_path=config.db_path)
    artifacts = get_session_artifacts("sess_audio", db_path=config.db_path)

    assert sessions[0]["status"] == "audio_acquired"
    assert {artifact["artifact_type"] for artifact in artifacts} == {
        "raw_audio",
        "acquisition_timing",
    }


def test_ble_runtime_waits_for_both_hands_before_recording(tmp_path, monkeypatch):
    import asyncio

    events: list[str] = []

    class FakeBleSource:
        def __init__(self, _config_path):
            pass

        async def run(self, stop_event, on_packet):
            for hand in ("L", "R"):
                events.append(f"imu_{hand}")
                await on_packet(_packet(hand))
            await stop_event.wait()

    class FakeRecorder:
        async def start(self, output_path):
            events.append("audio_start")
            output_path.write_bytes(b"RIFF")
            return AudioStartTiming(1784563200000, 1784563199999, 1784563200001)

        async def stop(self):
            events.append("audio_stop")

    class FakeSpeaker:
        async def say(self, message):
            events.append(f"say_{message}")

    monkeypatch.setattr(session_module, "BleHandSensorSource", FakeBleSource)
    config = RuntimeConfig(
        user_id="u_ble",
        user_name="BLE",
        piece_id="piece_ble",
        piece_title="BLE Test",
        piece_composer=None,
        session_id="sess_ble",
        data_root=tmp_path / "data",
        mode="ble",
        ble_config=tmp_path / "ble.json",
        duration_sec=0.01,
        target_bpm=None,
        db_path=tmp_path / "pianopal.sqlite3",
    )

    asyncio.run(run_session(config, audio_recorder=FakeRecorder(), speaker=FakeSpeaker()))

    assert events.index("imu_L") < events.index("audio_start")
    assert events.index("imu_R") < events.index("audio_start")
    assert events.index("say_session started") < events.index("audio_start")


def test_ble_runtime_starts_after_ready_timeout_with_missing_hand(tmp_path, monkeypatch):
    import asyncio

    events: list[str] = []

    class OneHandBleSource:
        def __init__(self, _config_path):
            pass

        async def run(self, stop_event, on_packet):
            await on_packet(_packet("L"))
            await stop_event.wait()

    class FakeRecorder:
        async def start(self, output_path):
            events.append("audio_start")
            output_path.write_bytes(b"RIFF")
            return AudioStartTiming(1784563200000, 1784563199999, 1784563200001)

        async def stop(self):
            events.append("audio_stop")

    monkeypatch.setattr(session_module, "BleHandSensorSource", OneHandBleSource)
    monkeypatch.setattr(session_module, "BLE_READY_TIMEOUT_SECONDS", 0.01)
    config = RuntimeConfig(
        user_id="u_ble_timeout",
        user_name="BLE Timeout",
        piece_id="piece_ble_timeout",
        piece_title="BLE Timeout Test",
        piece_composer=None,
        session_id="sess_ble_timeout",
        data_root=tmp_path / "data",
        mode="ble",
        ble_config=tmp_path / "ble.json",
        duration_sec=0.01,
        target_bpm=None,
        db_path=tmp_path / "pianopal.sqlite3",
    )

    paths = asyncio.run(run_session(config, audio_recorder=FakeRecorder()))

    assert events == ["audio_start", "audio_stop"]
    timing = json.loads(paths.timing_path.read_text(encoding="utf-8"))
    assert timing["imu"]["initial_missing_hands"] == ["R"]


def test_ble_runtime_reports_unexpected_source_failure(tmp_path, monkeypatch):
    import asyncio

    class FailingBleSource:
        def __init__(self, _config_path):
            pass

        async def run(self, _stop_event, _on_packet):
            raise RuntimeError("unexpected BLE worker failure")

    monkeypatch.setattr(session_module, "BleHandSensorSource", FailingBleSource)
    config = RuntimeConfig(
        user_id="u_ble_error",
        user_name="BLE Error",
        piece_id="piece_ble_error",
        piece_title="BLE Error Test",
        piece_composer=None,
        session_id="sess_ble_error",
        data_root=tmp_path / "data",
        mode="ble",
        ble_config=tmp_path / "ble.json",
        duration_sec=0.01,
        target_bpm=None,
        db_path=tmp_path / "pianopal.sqlite3",
    )

    with pytest.raises(RuntimeError, match="unexpected BLE worker failure"):
        asyncio.run(run_session(config))


def _packet(hand: str) -> RawHandSensorPacket:
    reading = SensorReading(
        accel=SensorVector(1.0, 2.0, 3.0),
        gyro=SensorVector(4.0, 5.0, 6.0),
    )
    return RawHandSensorPacket(
        hand=hand,  # type: ignore[arg-type]
        sequence_number=1,
        device_timestamp_ms=0,
        received_at_unix_ms=1784563200000,
        fingertip=reading,
        hand_back=reading,
        wrist=SensorReading(accel=SensorVector(7.0, 8.0, 9.0), gyro=None),
    )
