"""Speaker feedback adapters for Raspberry Pi runtime."""

from __future__ import annotations

import asyncio
import shlex


class Speaker:
    async def say(self, message: str) -> None:
        raise NotImplementedError


class ConsoleSpeaker(Speaker):
    async def say(self, message: str) -> None:
        print(f"[feedback] {message}")


class CommandSpeaker(Speaker):
    """Send feedback text to an external speech command.

    Example:

        espeak {message}
    """

    def __init__(self, command_template: str) -> None:
        self.command_template = command_template

    async def say(self, message: str) -> None:
        command = self.command_template.format(message=message)
        args = shlex.split(command)
        if not args:
            return

        process = await asyncio.create_subprocess_exec(*args)
        await process.wait()
