"""Top-level Raspberry Pi acquisition session orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import asyncio

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
from .posture import RealtimePosturePipeline
from .simulate import run_simulated_packets
from .speaker import ConsoleSpeaker, Speaker
from .storage import JsonlWriter, SessionPaths, make_session_paths


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
    pipeline = RealtimePosturePipeline()
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

    _register_artifacts(config.session_id, paths, started_at, config.db_path)
    model_run_id = f"modelrun_{config.session_id}_imu_posture"
    add_model_run(
        model_run_id,
        config.session_id,
        "imu_posture_classifier",
        pipeline.model.model_version,
        started_at,
        output_artifact_id=f"artifact_{config.session_id}_imu_predictions",
        db_path=config.db_path,
    )

    packet_counts = {"L": 0, "R": 0}
    prediction_count = 0

    async def handle_packet(packet: RawHandSensorPacket) -> None:
        nonlocal prediction_count
        packet_counts[packet.hand] += 1
        raw_writer = left_writer if packet.hand == "L" else right_writer
        raw_writer.write(packet.to_dict())

        prediction = pipeline.add_packet(packet)
        if prediction is not None:
            prediction_count += 1
            prediction_writer.write(prediction.to_dict())
            if prediction.predicted_label != "normal" and prediction.confidence >= 0.5:
                await feedback.say(f"{packet.hand} {prediction.predicted_label}")

    await feedback.say("session started")
    await recorder.start(paths.audio_path)

    try:
        with JsonlWriter(paths.imu_left_path) as left_writer, JsonlWriter(
            paths.imu_right_path
        ) as right_writer, JsonlWriter(paths.imu_predictions_path) as prediction_writer:
            if config.mode == "simulate":
                await run_simulated_packets(
                    stop_event,
                    handle_packet,
                    duration_sec=config.duration_sec,
                )
            elif config.mode == "ble":
                if config.ble_config is None:
                    raise ValueError("--ble-config is required in ble mode")
                await BleHandSensorSource(config.ble_config).run(stop_event, handle_packet)
            else:
                raise ValueError(f"unknown runtime mode: {config.mode}")
    finally:
        await recorder.stop()

    ended_at = utc_now_iso()
    finish_model_run(
        model_run_id,
        ended_at,
        output_artifact_id=f"artifact_{config.session_id}_imu_predictions",
        metrics={
            "left_packets": packet_counts["L"],
            "right_packets": packet_counts["R"],
            "predictions": prediction_count,
        },
        db_path=config.db_path,
    )
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
            }
        },
        status="acquired",
        db_path=config.db_path,
    )
    await feedback.say("session acquired")
    return paths


def _register_artifacts(
    session_id: str,
    paths: SessionPaths,
    created_at: str,
    db_path: Path | None,
) -> None:
    artifacts = [
        ("raw_audio", paths.audio_path),
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
