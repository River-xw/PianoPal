"""Audio recording adapters for Raspberry Pi acquisition."""

from __future__ import annotations

from pathlib import Path
import asyncio
import shlex


class AudioRecorder:
    """Minimal async audio-recorder interface."""

    async def start(self, output_path: Path) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError


class NullAudioRecorder(AudioRecorder):
    """No-op recorder used for simulation and tests."""

    async def start(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            "Audio was not recorded. Use --audio-command on Raspberry Pi.\n",
            encoding="utf-8",
        )

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

    async def start(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = self.command_template.format(output=str(output_path))
        args = shlex.split(command)
        if not args:
            raise ValueError("audio command is empty")

        self.process = await asyncio.create_subprocess_exec(*args)

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
