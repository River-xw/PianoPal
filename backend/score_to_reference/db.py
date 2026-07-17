"""Persist a canonical score reference to the backend DB (SQLAlchemy)."""
from __future__ import annotations

from typing import Any

# TODO(backend): import the real SQLAlchemy session + model here once the
# score-reference table exists, e.g.:
#
#   from backend.db.session import SessionLocal
#   from backend.db.models import ScoreReference


def save_to_db(reference: dict[str, Any]) -> None:
    """Insert a score reference dict (as returned by `convert`) into the backend DB.

    Stub -- wire up the SQLAlchemy model/session imports above, then replace
    the body with something like:

        session = SessionLocal()
        try:
            row = ScoreReference(
                title=reference["title"],
                tempo_bpm=reference["tempo_bpm"],
                time_signature=reference["time_signature"],
                key=reference["key"],
                duration_sec=reference["duration_sec"],
                notes_json=reference["notes"],  # JSON column
            )
            session.add(row)
            session.commit()
        finally:
            session.close()
    """
    raise NotImplementedError(
        "save_to_db is a stub. Wire up the backend's SQLAlchemy model/session "
        "for score references, then implement the insert here."
    )
