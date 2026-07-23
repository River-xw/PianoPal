"""Audio recording adapters for Raspberry Pi acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import asyncio
import shlex
import time


@dataclass(frozen=True)
class AudioStartTiming:
    """Best available wall-clock estimate for the beginning of recording."""

    estimated_unix_ms: int
    before_start_unix_ms: int
    after_start_unix_ms: int


class AudioRecorder:
    """Minimal async audio-recorder interface."""

    async def start(self, output_path: Path) -> AudioStartTiming:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError


class NullAudioRecorder(AudioRecorder):
    """No-op recorder used for simulation and tests."""

    async def start(self, output_path: Path) -> AudioStartTiming:
        before_start_unix_ms = time.time_ns() // 1_000_000
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            "Audio was not recorded. Use --audio-command on Raspberry Pi.\n",
            encoding="utf-8",
        )
        after_start_unix_ms = time.time_ns() // 1_000_000
        return _make_start_timing(before_start_unix_ms, after_start_unix_ms)

    async def stop(self) -> None:
        return None


class CommandAudioRecorder(AudioRecorder):
    """Run an external recorder such as arecord.

    The command may contain ``{output}``, which is replaced with the target WAV
    path. Example:

        arecord -f cd -t wav {output}
    """

    def __init__(self, command_template: str) -> None:
        self.command_template = command_template
        self.process: asyncio.subprocess.Process | None = None

    async def start(self, output_path: Path) -> AudioStartTiming:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = self.command_template.format(output=str(output_path))
        args = shlex.split(command)
        if not args:
            raise ValueError("audio command is empty")

        before_start_unix_ms = time.time_ns() // 1_000_000
        self.process = await asyncio.create_subprocess_exec(*args)
        after_start_unix_ms = time.time_ns() // 1_000_000
        return _make_start_timing(before_start_unix_ms, after_start_unix_ms)

    async def stop(self) -> None:
        if self.process is None:
            return

        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

        self.process = None


def _make_start_timing(before_start_unix_ms: int, after_start_unix_ms: int) -> AudioStartTiming:
    return AudioStartTiming(
        estimated_unix_ms=(before_start_unix_ms + after_start_unix_ms) // 2,
        before_start_unix_ms=before_start_unix_ms,
        after_start_unix_ms=after_start_unix_ms,
    )
