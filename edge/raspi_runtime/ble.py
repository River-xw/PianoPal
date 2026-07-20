"""BLE hand-sensor source for Raspberry Pi runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable
import asyncio
import json
import time

from backend.sensors import RawHandSensorPacket, parse_hand_sensor_packet


PacketHandler = Callable[[RawHandSensorPacket], Awaitable[None]]

UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
UART_TX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
UART_RX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


def load_devices(config_path: Path) -> list[dict[str, str]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    devices = config.get("devices")
    if not isinstance(devices, list) or not devices:
        raise ValueError('config must contain a non-empty "devices" list')
    return devices


class BleHandSensorSource:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    async def run(self, stop_event: asyncio.Event, on_packet: PacketHandler) -> None:
        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise RuntimeError("Install bleak on the Raspberry Pi to use BLE mode") from exc

        devices = load_devices(self.config_path)
        tasks = [
            asyncio.create_task(
                self._connect_device(BleakClient, device, stop_event, on_packet)
            )
            for device in devices
        ]
        await asyncio.gather(*tasks)

    async def _connect_device(
        self,
        bleak_client_cls,
        device: dict[str, str],
        stop_event: asyncio.Event,
        on_packet: PacketHandler,
    ) -> None:
        name = device["name"]
        address = device["address"]
        hand = device["hand"].upper()

        while not stop_event.is_set():
            receive_buffer = ""

            def on_data(_sender, data: bytearray) -> None:
                nonlocal receive_buffer
                receive_buffer += bytes(data).decode("utf-8", errors="replace")
                while "\n" in receive_buffer:
                    line, receive_buffer = receive_buffer.split("\n", 1)
                    packet = parse_hand_sensor_packet(
                        line.rstrip("\r"),
                        received_at_unix_ms=time.time_ns() // 1_000_000,
                    )
                    if packet is not None:
                        asyncio.create_task(on_packet(packet))

            try:
                print(f"[{name}] connecting to {address}")
                async with bleak_client_cls(address, timeout=20) as client:
                    service = client.services.get_service(UART_SERVICE_UUID)
                    if service is None:
                        raise RuntimeError("micro:bit UART service was not found")

                    await client.start_notify(UART_TX_UUID, on_data)
                    await client.write_gatt_char(UART_RX_UUID, b"CONNECT\n", response=False)
                    await asyncio.sleep(0.5)
                    await client.write_gatt_char(
                        UART_RX_UUID,
                        f"START {hand}\n".encode("utf-8"),
                        response=False,
                    )

                    while client.is_connected and not stop_event.is_set():
                        await asyncio.sleep(0.2)

                    if client.is_connected:
                        await client.write_gatt_char(UART_RX_UUID, b"STOP\n", response=False)
                        await client.stop_notify(UART_TX_UUID)
            except Exception as error:
                print(f"[{name}] BLE error: {error}")

            if not stop_event.is_set():
                await asyncio.sleep(5)
