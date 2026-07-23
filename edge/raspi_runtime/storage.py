"""Local session storage helpers for Raspberry Pi acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json


@dataclass(frozen=True)
class SessionPaths:
    session_id: str
    raw_dir: Path
    artifacts_dir: Path
    audio_path: Path
    timing_path: Path
    imu_left_path: Path
    imu_right_path: Path
    imu_predictions_path: Path


class JsonlWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.file = None

    def __enter__(self) -> "JsonlWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a", encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.file is not None:
            self.file.close()

    def write(self, record: dict[str, Any]) -> None:
        if self.file is None:
            raise RuntimeError("JsonlWriter is not open")
        self.file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self.file.flush()


def make_session_paths(data_root: Path, session_id: str) -> SessionPaths:
    raw_dir = data_root / "raw" / "sessions" / session_id
    artifacts_dir = data_root / "artifacts" / "sessions" / session_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    return SessionPaths(
        session_id=session_id,
        raw_dir=raw_dir,
        artifacts_dir=artifacts_dir,
        audio_path=raw_dir / "audio.wav",
        timing_path=raw_dir / "timing.json",
        imu_left_path=raw_dir / "imu_left.jsonl",
        imu_right_path=raw_dir / "imu_right.jsonl",
        imu_predictions_path=artifacts_dir / "imu_predictions.jsonl",
    )
