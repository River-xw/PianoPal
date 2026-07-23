"""Top-level Raspberry Pi acquisition session orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import asyncio
import json
import time

from backend.db import (
    add_artifact,
    add_model_run,
    create_piece,
    create_practice_session,
    create_user,
    finish_model_run,
    finish_practice_session,
    init_db,
)
from backend.sensors import RawHandSensorPacket

from .audio import AudioRecorder, NullAudioRecorder
from .ble import BleHandSensorSource
from .posture import RealtimePosturePipeline, load_posture_model
from .simulate import run_simulated_packets
from .speaker import ConsoleSpeaker, Speaker
from .storage import JsonlWriter, SessionPaths, make_session_paths


BLE_READY_TIMEOUT_SECONDS = 45.0


@dataclass(frozen=True)
class RuntimeConfig:
    user_id: str
    user_name: str | None
    piece_id: str
    piece_title: str
    piece_composer: str | None
    session_id: str
    data_root: Path
    mode: str
    ble_config: Path | None
    duration_sec: float
    target_bpm: int | None
    db_path: Path | None = None
    posture_model_path: Path | None = None
    posture_hands: tuple[str, ...] | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_session_id() -> str:
    return "sess_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


async def run_session(
    config: RuntimeConfig,
    audio_recorder: AudioRecorder | None = None,
    speaker: Speaker | None = None,
) -> SessionPaths:
    paths = make_session_paths(config.data_root, config.session_id)
    recorder = audio_recorder or NullAudioRecorder()
    feedback = speaker or ConsoleSpeaker()
    posture_model = load_posture_model(config.posture_model_path)
    pipeline = RealtimePosturePipeline(
        model=posture_model,
        window_ms=2000 if config.posture_model_path is not None else 800,
    )
    posture_hands = set(config.posture_hands) if config.posture_hands else {"L", "R"}
    stop_event = asyncio.Event()

    init_db(config.db_path)
    started_at = utc_now_iso()
    create_user(config.user_id, config.user_name, started_at, config.db_path)
    create_piece(
        config.piece_id,
        config.piece_title,
        config.piece_composer,
        None,
        started_at,
        config.db_path,
    )
    create_practice_session(
        config.session_id,
        config.user_id,
        config.piece_id,
        started_at,
        target_bpm=config.target_bpm,
        status="acquiring",
        db_path=config.db_path,
    )

    _register_audio_artifact(config.session_id, paths, started_at, config.db_path)
    if config.mode != "audio-only":
        _register_imu_artifacts(config.session_id, paths, started_at, config.db_path)

    model_run_id = f"modelrun_{config.session_id}_imu_posture"
    if config.mode != "audio-only":
        add_model_run(
            model_run_id,
            config.session_id,
            pipeline.model.model_name,
            pipeline.model.model_version,
            started_at,
            output_artifact_id=f"artifact_{config.session_id}_imu_predictions",
            db_path=config.db_path,
        )

    packet_counts = {"L": 0, "R": 0}
    packet_timing: dict[str, dict[str, int]] = {"L": {}, "R": {}}
    ready_hands: set[str] = set()
    sensors_ready = asyncio.Event()
    initial_missing_hands: list[str] = []
    prediction_count = 0

    async def handle_packet(packet: RawHandSensorPacket) -> None:
        nonlocal prediction_count
        packet_counts[packet.hand] += 1
        ready_hands.add(packet.hand)
        if ready_hands == {"L", "R"}:
            sensors_ready.set()
        hand_timing = packet_timing[packet.hand]
        hand_timing.setdefault("first_device_timestamp_ms", packet.device_timestamp_ms)
        hand_timing.setdefault("first_received_at_unix_ms", packet.received_at_unix_ms)
        hand_timing["last_device_timestamp_ms"] = packet.device_timestamp_ms
        hand_timing["last_received_at_unix_ms"] = packet.received_at_unix_ms
        raw_writer = left_writer if packet.hand == "L" else right_writer
        raw_writer.write(packet.to_dict())

        prediction = pipeline.add_packet(packet) if packet.hand in posture_hands else None
        if prediction is not None:
            prediction_count += 1
            prediction_writer.write(prediction.to_dict())
            if prediction.predicted_label != "normal" and prediction.confidence >= 0.5:
                await feedback.say(f"{packet.hand} {prediction.predicted_label}")

    async def start_recording() -> dict[str, Any]:
        await feedback.say("session started")
        audio_start = await recorder.start(paths.audio_path)
        metadata: dict[str, Any] = {
            "schema_version": "audio_imu_timing_v1",
            "session_id": config.session_id,
            "audio": {
                "started_at_unix_ms": audio_start.estimated_unix_ms,
                "start_before_recorder_unix_ms": audio_start.before_start_unix_ms,
                "start_after_recorder_unix_ms": audio_start.after_start_unix_ms,
                "start_uncertainty_ms": (
                    audio_start.after_start_unix_ms - audio_start.before_start_unix_ms
                ),
            },
            "imu": {
                "alignment_method": "median_received_minus_device_timestamp",
                "hands": packet_timing,
                "initial_missing_hands": initial_missing_hands,
            },
        }
        _write_timing_metadata(paths.timing_path, metadata)
        return metadata

    timing_metadata: dict[str, Any] | None = None
    try:
        if config.mode == "audio-only":
            timing_metadata = await start_recording()
            await asyncio.sleep(config.duration_sec)
        else:
            with JsonlWriter(paths.imu_left_path) as left_writer, JsonlWriter(
                paths.imu_right_path
            ) as right_writer, JsonlWriter(paths.imu_predictions_path) as prediction_writer:
                if config.mode == "simulate":
                    timing_metadata = await start_recording()
                    await run_simulated_packets(
                        stop_event,
                        handle_packet,
                        duration_sec=config.duration_sec,
                    )
                elif config.mode == "ble":
                    if config.ble_config is None:
                        raise ValueError("--ble-config is required in ble mode")
                    ble_task = asyncio.create_task(
                        BleHandSensorSource(config.ble_config).run(stop_event, handle_packet)
                    )
                    ready_task = asyncio.create_task(sensors_ready.wait())
                    try:
                        completed, _ = await asyncio.wait(
                            {ready_task, ble_task},
                            timeout=BLE_READY_TIMEOUT_SECONDS,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if ble_task in completed:
                            await ble_task
                        if ready_task not in completed:
                            initial_missing_hands.extend(
                                sorted({"L", "R"} - ready_hands)
                            )
                            print(
                                "Warning: timed out waiting for initial IMU packets "
                                f"from {', '.join(initial_missing_hands)}; "
                                "starting recording and continuing BLE retries"
                            )
                        timing_metadata = await start_recording()
                        completed, _ = await asyncio.wait(
                            {ble_task},
                            timeout=config.duration_sec,
                        )
                        if ble_task in completed:
                            await ble_task
                    finally:
                        if not ready_task.done():
                            ready_task.cancel()
                        await asyncio.gather(ready_task, return_exceptions=True)
                        stop_event.set()
                        await asyncio.gather(ble_task, return_exceptions=True)
                else:
                    raise ValueError(f"unknown runtime mode: {config.mode}")
    finally:
        if timing_metadata is not None:
            await recorder.stop()
            timing_metadata["audio"]["stopped_at_unix_ms"] = time.time_ns() // 1_000_000
            _write_timing_metadata(paths.timing_path, timing_metadata)

    ended_at = utc_now_iso()
    if config.mode != "audio-only":
        finish_model_run(
            model_run_id,
            ended_at,
            output_artifact_id=f"artifact_{config.session_id}_imu_predictions",
            metrics={
                "left_packets": packet_counts["L"],
                "right_packets": packet_counts["R"],
                "predictions": prediction_count,
                "posture_hands": sorted(posture_hands),
            },
            db_path=config.db_path,
        )

    status = "audio_acquired" if config.mode == "audio-only" else "acquired"
    finish_practice_session(
        config.session_id,
        ended_at,
        score=None,
        summary={
            "acquisition": {
                "left_packets": packet_counts["L"],
                "right_packets": packet_counts["R"],
                "imu_predictions": prediction_count,
                "audio_uri": str(paths.audio_path),
                "timing_uri": str(paths.timing_path),
                "mode": config.mode,
                "posture_model": str(config.posture_model_path)
                if config.posture_model_path is not None
                else pipeline.model.model_version,
                "posture_hands": sorted(posture_hands),
            }
        },
        status=status,
        db_path=config.db_path,
    )
    await feedback.say(status)
    return paths


def _register_audio_artifact(
    session_id: str,
    paths: SessionPaths,
    created_at: str,
    db_path: Path | None,
) -> None:
    add_artifact(
        f"artifact_{session_id}_raw_audio",
        session_id,
        "raw_audio",
        str(paths.audio_path),
        created_at,
        db_path,
    )
    add_artifact(
        f"artifact_{session_id}_acquisition_timing",
        session_id,
        "acquisition_timing",
        str(paths.timing_path),
        created_at,
        db_path,
    )


def _write_timing_metadata(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _register_imu_artifacts(
    session_id: str,
    paths: SessionPaths,
    created_at: str,
    db_path: Path | None,
) -> None:
    artifacts = [
        ("imu_left_raw", paths.imu_left_path),
        ("imu_right_raw", paths.imu_right_path),
        ("imu_predictions", paths.imu_predictions_path),
    ]
    for artifact_type, path in artifacts:
        add_artifact(
            f"artifact_{session_id}_{artifact_type}",
            session_id,
            artifact_type,
            str(path),
            created_at,
            db_path,
        )
