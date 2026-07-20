"""Small SQLite persistence layer for local PianoPal runs.

SQLite is used as the local structured index: it stores users, pieces,
practice sessions, artifact paths, and model-run metadata. Large files such as
audio, raw IMU streams, and full result JSON artifacts should stay in data/.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
import json
import sqlite3


REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "db" / "pianopal.sqlite3"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _dump_json(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with PianoPal's expected defaults."""

    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def transaction(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Run a short DB operation and always close the connection."""

    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> None:
    """Create the local SQLite database and all known tables."""

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with transaction(db_path) as conn:
        conn.executescript(schema)


def create_user(
    user_id: str,
    name: str | None,
    created_at: str,
    db_path: Path | str | None = None,
) -> None:
    """Insert a user if it does not already exist."""

    with transaction(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO users (id, name, created_at)
            VALUES (?, ?, ?)
            """,
            (user_id, name, created_at),
        )


def create_piece(
    piece_id: str,
    title: str,
    composer: str | None,
    reference_uri: str | None,
    created_at: str,
    db_path: Path | str | None = None,
) -> None:
    """Insert or update one score/piece record."""

    with transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO pieces (id, title, composer, reference_uri, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                composer = excluded.composer,
                reference_uri = excluded.reference_uri
            """,
            (piece_id, title, composer, reference_uri, created_at),
        )


def create_practice_session(
    session_id: str,
    user_id: str,
    piece_id: str,
    started_at: str,
    target_bpm: int | None = None,
    status: str = "recording",
    db_path: Path | str | None = None,
) -> None:
    """Create one practice session before acquisition or scoring starts."""

    with transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO practice_sessions
                (id, user_id, piece_id, started_at, target_bpm, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, piece_id, started_at, target_bpm, status),
        )


def add_artifact(
    artifact_id: str,
    session_id: str,
    artifact_type: str,
    uri: str,
    created_at: str,
    db_path: Path | str | None = None,
) -> None:
    """Record a file generated or consumed by a practice session."""

    with transaction(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO artifacts
                (id, session_id, artifact_type, uri, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (artifact_id, session_id, artifact_type, uri, created_at),
        )


def add_model_run(
    run_id: str,
    session_id: str,
    model_name: str,
    model_version: str,
    started_at: str,
    input_artifact_id: str | None = None,
    output_artifact_id: str | None = None,
    metrics: dict[str, Any] | None = None,
    db_path: Path | str | None = None,
) -> None:
    """Record one model inference/training run, such as IMU posture inference."""

    with transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO model_runs
                (
                    id, session_id, model_name, model_version,
                    input_artifact_id, output_artifact_id,
                    started_at, metrics_json
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                session_id,
                model_name,
                model_version,
                input_artifact_id,
                output_artifact_id,
                started_at,
                _dump_json(metrics),
            ),
        )


def finish_model_run(
    run_id: str,
    ended_at: str,
    output_artifact_id: str | None = None,
    metrics: dict[str, Any] | None = None,
    db_path: Path | str | None = None,
) -> None:
    """Mark a model run as complete and optionally attach output metadata."""

    with transaction(db_path) as conn:
        conn.execute(
            """
            UPDATE model_runs
            SET ended_at = ?,
                output_artifact_id = COALESCE(?, output_artifact_id),
                metrics_json = COALESCE(?, metrics_json)
            WHERE id = ?
            """,
            (ended_at, output_artifact_id, _dump_json(metrics), run_id),
        )


def finish_practice_session(
    session_id: str,
    ended_at: str,
    score: float,
    summary: dict[str, Any],
    status: str = "completed",
    db_path: Path | str | None = None,
) -> None:
    """Store the final score summary for a completed practice session."""

    with transaction(db_path) as conn:
        conn.execute(
            """
            UPDATE practice_sessions
            SET ended_at = ?,
                score = ?,
                summary_json = ?,
                status = ?
            WHERE id = ?
            """,
            (ended_at, score, _dump_json(summary), status, session_id),
        )


def get_recent_sessions(
    user_id: str,
    limit: int = 10,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return recent practice sessions for one user."""

    with transaction(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                practice_sessions.*,
                pieces.title AS piece_title,
                pieces.composer AS piece_composer
            FROM practice_sessions
            JOIN pieces ON pieces.id = practice_sessions.piece_id
            WHERE practice_sessions.user_id = ?
            ORDER BY practice_sessions.started_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def get_session_artifacts(
    session_id: str,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return all artifact paths recorded for one practice session."""

    with transaction(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM artifacts
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()

    return [dict(row) for row in rows]


if __name__ == "__main__":
    init_db()
    print(f"Initialized SQLite database at {DB_PATH}")
