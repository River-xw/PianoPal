"""Simulation source for local development without Raspberry Pi hardware."""

from __future__ import annotations

import asyncio
import time

from backend.sensors import parse_hand_sensor_packet

from .ble import PacketHandler


async def run_simulated_packets(
    stop_event: asyncio.Event,
    on_packet: PacketHandler,
    duration_sec: float,
    sample_interval_sec: float = 0.1,
) -> None:
    start = time.monotonic()
    seq = {"L": 0, "R": 0}

    while not stop_event.is_set():
        elapsed = time.monotonic() - start
        if elapsed >= duration_sec:
            stop_event.set()
            break

        for hand in ("L", "R"):
            seq[hand] += 1
            timestamp_ms = int(elapsed * 1000)
            gyro = 16.0 if hand == "R" and 1.0 < elapsed < 1.8 else 2.0
            line = (
                f"{hand},{seq[hand]},{timestamp_ms},"
                f"120,-84,16320,3.2,{gyro},1.8,"
                f"98,-70,16288,2.1,{gyro / 2},1.2,"
                f"110,-66,16310"
            )
            packet = parse_hand_sensor_packet(
                line,
                received_at_unix_ms=time.time_ns() // 1_000_000,
            )
            if packet is not None:
                await on_packet(packet)

        await asyncio.sleep(sample_interval_sec)
