from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.sensors import RawHandSensorPacket, SensorReading, SensorVector
import edge.posture_capture as posture_capture_module
import edge.practice_server as practice_server_module
from edge.posture_capture import (
    _run,
    _run_source_until_stopped,
    _write_result,
)
from edge.practice_server import (
    FORMAL_DATA_DIR,
    _start_posture_capture_and_wait,
    _stop_posture_capture,
    _unavailable_motion_assessment,
)
from edge.raspi_runtime.ble import load_devices
from edge.raspi_runtime.cli import TRAINING_DATA_ROOT


def test_formal_and_training_roots_are_disjoint():
    assert FORMAL_DATA_DIR != TRAINING_DATA_ROOT
    assert FORMAL_DATA_DIR.name == "formal_assessments"
    assert TRAINING_DATA_ROOT.name == "training_collection"


def test_motion_capture_result_exposes_real_score(tmp_path):
    output = tmp_path / "motion.json"

    _write_result(
        output,
        total=10,
        normal=7,
        label_counts={"normal": 7, "wrist_collapse": 3},
        capture_hands=["L"],
        model_name="left_hand_posture_classifier",
        model_version="test",
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["available"] is True
    assert result["motion_score"] == 70.0
    assert result["hand_shape_score"] == 70.0
    assert result["capture_hands"] == ["L"]


def test_unavailable_motion_has_no_placeholder_score():
    result = _unavailable_motion_assessment("sensor missing")

    assert result["available"] is False
    assert result["motion_score"] is None
    assert result["hand_shape_score"] is None


def test_unavailable_motion_is_still_persisted_for_formal_audit(tmp_path):
    class SessionStub:
        posture_process = None
        motion_unavailable_reason = "sensor missing"
        posture_result_path = tmp_path / "motion_assessment.json"

    result = _stop_posture_capture(SessionStub())

    assert result["available"] is False
    assert SessionStub.posture_result_path.exists()
    assert json.loads(
        SessionStub.posture_result_path.read_text(encoding="utf-8")
    )["motion_score"] is None


def test_formal_ble_source_filters_only_requested_hands(tmp_path):
    config = tmp_path / "ble.json"
    config.write_text(json.dumps({
        "devices": [
            {"name": "left", "hand": "left", "address": "LEFT"},
            {"name": "right", "hand": "right", "address": "RIGHT"},
        ]
    }), encoding="utf-8")

    assert [device["name"] for device in load_devices(config, {"L"})] == ["left"]
    assert [device["name"] for device in load_devices(config, {"R"})] == ["right"]
    assert [device["name"] for device in load_devices(config, {"L", "R"})] == [
        "left",
        "right",
    ]
    # Training collection keeps the existing all-configured-devices behavior.
    assert len(load_devices(config)) == 2


def test_motion_shutdown_cancels_stuck_ble_and_returns():
    class StuckBleSource:
        def __init__(self):
            self.cancelled = False

        async def run(self, _stop_event, _on_packet):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    async def exercise():
        source = StuckBleSource()
        stop_event = asyncio.Event()
        stop_event.set()
        await _run_source_until_stopped(
            source,
            stop_event,
            lambda _packet: None,
            shutdown_grace_seconds=0.01,
        )
        return source

    source = asyncio.run(exercise())
    assert source.cancelled is True


def _sensor_packet(hand: str, sequence_number: int) -> RawHandSensorPacket:
    reading = SensorReading(
        accel=SensorVector(1.0, 2.0, 3.0),
        gyro=SensorVector(4.0, 5.0, 6.0),
    )
    return RawHandSensorPacket(
        hand=hand,  # type: ignore[arg-type]
        sequence_number=sequence_number,
        device_timestamp_ms=sequence_number * 100,
        received_at_unix_ms=1784563200000 + sequence_number * 100,
        fingertip=reading,
        hand_back=reading,
        wrist=SensorReading(
            accel=SensorVector(7.0, 8.0, 9.0),
            gyro=None,
        ),
    )


def test_posture_capture_writes_ready_after_real_packet_stream(
    tmp_path, monkeypatch
):
    requested_hands = []

    class FakeBleSource:
        def __init__(self, _config_path, hands=None):
            requested_hands.extend(sorted(hands or []))

        async def run(self, stop_event, on_packet):
            for sequence in range(4):
                await on_packet(_sensor_packet("L", sequence))
            stop_event.set()

    monkeypatch.setattr(
        posture_capture_module, "BleHandSensorSource", FakeBleSource
    )
    config_path = tmp_path / "ble.json"
    config_path.write_text('{"devices": [{}]}', encoding="utf-8")
    ready_path = tmp_path / "ready.json"
    result_path = tmp_path / "result.json"
    args = SimpleNamespace(
        hands=["L"],
        ble_config=config_path,
        posture_model=None,
        start_delay_sec=0,
        ready_output=ready_path,
        output=result_path,
    )

    asyncio.run(_run(args))

    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert requested_hands == ["L"]
    assert ready["ready"] is True
    assert ready["capture_hands"] == ["L"]
    assert result["total_predictions"] > 0


def test_practice_gate_waits_for_all_configured_hands(
    tmp_path, monkeypatch
):
    class FakeProcess:
        def poll(self):
            return None

    class SessionStub:
        posture_ready_path = tmp_path / "motion_ready.json"
        posture_result_path = tmp_path / "motion_assessment.json"
        posture_log_path = tmp_path / "motion_capture.log"
        posture_process = None

    def fake_popen(*_args, **_kwargs):
        SessionStub.posture_ready_path.write_text(json.dumps({
            "ready": True,
            "capture_hands": ["L", "R"],
        }), encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(practice_server_module, "POSTURE_HANDS", ("L", "R"))
    monkeypatch.setattr(practice_server_module.subprocess, "Popen", fake_popen)

    session = SessionStub()
    _start_posture_capture_and_wait(
        session,
        tmp_path / "model.json",
        timeout_sec=0.1,
    )

    assert session.posture_process is not None


def test_practice_gate_aborts_before_guide_when_ble_never_ready(
    tmp_path, monkeypatch
):
    class FakeProcess:
        def __init__(self):
            self.running = True
            self.terminated = False

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            self.terminated = True
            self.running = False

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.running = False

    class SessionStub:
        posture_ready_path = tmp_path / "motion_ready.json"
        posture_result_path = tmp_path / "motion_assessment.json"
        posture_log_path = tmp_path / "motion_capture.log"
        posture_process = None

    process = FakeProcess()
    monkeypatch.setattr(
        practice_server_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )

    session = SessionStub()
    with pytest.raises(TimeoutError, match="motion sensors were not ready"):
        _start_posture_capture_and_wait(
            session,
            tmp_path / "model.json",
            timeout_sec=0,
        )

    assert process.terminated is True
    assert not session.posture_ready_path.exists()
