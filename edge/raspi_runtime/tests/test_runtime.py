from __future__ import annotations

import json

from backend.db import get_recent_sessions, get_session_artifacts
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

    left_lines = paths.imu_left_path.read_text(encoding="utf-8").splitlines()
    prediction_lines = paths.imu_predictions_path.read_text(encoding="utf-8").splitlines()

    assert left_lines
    assert json.loads(left_lines[0])["schema_version"] == "hand_imu_raw_v2"
    assert prediction_lines
    assert json.loads(prediction_lines[0])["schema_version"] == "imu_posture_prediction_v1"

    sessions = get_recent_sessions("u_test", db_path=config.db_path)
    artifacts = get_session_artifacts("sess_test", db_path=config.db_path)

    assert sessions[0]["status"] == "acquired"
    assert sessions[0]["summary_json"] is not None
    assert {artifact["artifact_type"] for artifact in artifacts} == {
        "raw_audio",
        "imu_left_raw",
        "imu_right_raw",
        "imu_predictions",
    }
