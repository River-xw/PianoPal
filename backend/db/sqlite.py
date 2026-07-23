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
        # schema.sql's CREATE TABLE IF NOT EXISTS won't add a column to an
        # already-existing practice_sessions table from before `mode`
        # existed -- ALTER TABLE covers that case; harmless/no-op on a fresh
        # DB (schema.sql already created the column) or one that already has it.
        try:
            conn.execute("ALTER TABLE practice_sessions ADD COLUMN mode TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists


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
    mode: str | None = None,
    db_path: Path | str | None = None,
) -> None:
    """Create one practice session before acquisition or scoring starts."""

    with transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO practice_sessions
                (id, user_id, piece_id, started_at, target_bpm, status, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, piece_id, started_at, target_bpm, status, mode),
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
    score: float | None,
    summary: dict[str, Any] | None,
    status: str = "completed",
    db_path: Path | str | None = None,
) -> None:
    """Store the final score summary or acquisition status for a session."""

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
    mode: str | None = None,
    piece_id: str | None = None,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return recent practice sessions for one user, optionally filtered by
    mode ("learn"/"perform") and/or piece_id -- both default to no filter."""

    clauses = ["practice_sessions.user_id = ?"]
    params: list[Any] = [user_id]
    if mode is not None:
        clauses.append("practice_sessions.mode = ?")
        params.append(mode)
    if piece_id is not None:
        clauses.append("practice_sessions.piece_id = ?")
        params.append(piece_id)
    params.append(limit)

    with transaction(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                practice_sessions.*,
                pieces.title AS piece_title,
                pieces.composer AS piece_composer
            FROM practice_sessions
            JOIN pieces ON pieces.id = practice_sessions.piece_id
            WHERE {' AND '.join(clauses)}
            ORDER BY practice_sessions.started_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [dict(row) for row in rows]


def get_session(
    session_id: str,
    db_path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Return one practice session (joined with its piece title), or None."""

    with transaction(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                practice_sessions.*,
                pieces.title AS piece_title,
                pieces.composer AS piece_composer
            FROM practice_sessions
            JOIN pieces ON pieces.id = practice_sessions.piece_id
            WHERE practice_sessions.id = ?
            """,
            (session_id,),
        ).fetchone()

    return dict(row) if row is not None else None


def delete_session(
    session_id: str,
    db_path: Path | str | None = None,
) -> None:
    """Delete one practice session and its artifact/model-run records
    (NOT the underlying files those artifacts point at -- the caller is
    responsible for removing those, since this module only indexes paths)."""

    with transaction(db_path) as conn:
        conn.execute("DELETE FROM model_runs WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM artifacts WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM practice_sessions WHERE id = ?", (session_id,))


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


def count_sessions(
    user_id: str,
    db_path: Path | str | None = None,
) -> int:
    """Total number of practice sessions this user has ever started (any
    mode/status) -- used for the home/"我的" profile summary."""

    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM practice_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    return int(row["n"])


def recent_average_score(
    user_id: str,
    limit: int = 10,
    db_path: Path | str | None = None,
) -> float | None:
    """Average score over this user's most recent completed sessions (None
    if they have none yet)."""

    with transaction(db_path) as conn:
        rows = conn.execute(
            """
            SELECT score
            FROM practice_sessions
            WHERE user_id = ? AND status = 'completed' AND score IS NOT NULL
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

    scores = [row["score"] for row in rows]
    return sum(scores) / len(scores) if scores else None


def most_frequent_piece(
    user_id: str,
    db_path: Path | str | None = None,
) -> dict[str, Any] | None:
    """This user's most-practiced piece (by session count), or None if they
    have no sessions yet."""

    with transaction(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                practice_sessions.piece_id AS piece_id,
                pieces.title AS title,
                COUNT(*) AS count
            FROM practice_sessions
            JOIN pieces ON pieces.id = practice_sessions.piece_id
            WHERE practice_sessions.user_id = ?
            GROUP BY practice_sessions.piece_id
            ORDER BY count DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

    return dict(row) if row is not None else None


if __name__ == "__main__":
    init_db()
    print(f"Initialized SQLite database at {DB_PATH}")
