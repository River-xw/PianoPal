from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.db.sqlite import (
    add_artifact,
    add_model_run,
    create_piece,
    create_practice_session,
    create_user,
    finish_model_run,
    finish_practice_session,
    get_recent_sessions,
    get_session_artifacts,
    init_db,
)


def test_practice_session_roundtrip(tmp_path):
    db_path = tmp_path / "pianopal.sqlite3"
    init_db(db_path)

    create_user(
        "u_local_001",
        "River",
        "2026-07-20T10:30:00+08:00",
        db_path,
    )
    create_piece(
        "piece_fur_elise",
        "Fur Elise",
        "Beethoven",
        "data/artifacts/pieces/piece_fur_elise/reference.json",
        "2026-07-20T10:30:01+08:00",
        db_path,
    )
    create_practice_session(
        "sess_001",
        "u_local_001",
        "piece_fur_elise",
        "2026-07-20T10:31:00+08:00",
        target_bpm=80,
        db_path=db_path,
    )
    add_artifact(
        "artifact_result",
        "sess_001",
        "scoring_result",
        "data/artifacts/sessions/sess_001/result.json",
        "2026-07-20T10:35:00+08:00",
        db_path,
    )
    add_model_run(
        "run_imu_001",
        "sess_001",
        "imu_posture_classifier",
        "v1",
        "2026-07-20T10:34:00+08:00",
        output_artifact_id="artifact_result",
        metrics={"windows": 42},
        db_path=db_path,
    )
    finish_model_run(
        "run_imu_001",
        "2026-07-20T10:34:10+08:00",
        metrics={"windows": 42, "wrist_tension": 3},
        db_path=db_path,
    )
    finish_practice_session(
        "sess_001",
        "2026-07-20T10:36:00+08:00",
        82.5,
        {"score": 82.5, "counts": {"correct": 120}},
        db_path=db_path,
    )

    sessions = get_recent_sessions("u_local_001", db_path=db_path)
    artifacts = get_session_artifacts("sess_001", db_path=db_path)

    assert sessions[0]["id"] == "sess_001"
    assert sessions[0]["piece_title"] == "Fur Elise"
    assert sessions[0]["score"] == 82.5
    assert sessions[0]["status"] == "completed"
    assert artifacts[0]["artifact_type"] == "scoring_result"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
