"""Local database helpers for PianoPal."""

from .sqlite import (
    add_artifact,
    add_model_run,
    count_sessions,
    create_piece,
    create_practice_session,
    create_user,
    delete_session,
    finish_model_run,
    finish_practice_session,
    get_recent_sessions,
    get_session,
    get_session_artifacts,
    init_db,
    most_frequent_piece,
    recent_average_score,
)

__all__ = [
    "add_artifact",
    "add_model_run",
    "count_sessions",
    "create_piece",
    "create_practice_session",
    "create_user",
    "delete_session",
    "finish_model_run",
    "finish_practice_session",
    "get_recent_sessions",
    "get_session",
    "get_session_artifacts",
    "init_db",
    "most_frequent_piece",
    "recent_average_score",
]
