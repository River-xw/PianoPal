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
CONNECT_ATTEMPT_GAP_SECONDS = 1
CONNECT_TIMEOUT_SECONDS = 12
RECONNECT_DELAY_SECONDS = 2


def _short_hand(value: str) -> str:
    hand = str(value).strip().upper()
    return {"LEFT": "L", "RIGHT": "R"}.get(hand, hand)


def load_devices(
    config_path: Path,
    hands: set[str] | frozenset[str] | None = None,
) -> list[dict[str, str]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    devices = config.get("devices")
    if not isinstance(devices, list) or not devices:
        raise ValueError('config must contain a non-empty "devices" list')
    if hands is not None:
        wanted = {_short_hand(hand) for hand in hands}
        devices = [
            device
            for device in devices
            if _short_hand(device.get("hand", "")) in wanted
        ]
        if not devices:
            raise ValueError(
                f"config has no devices for requested hands {sorted(wanted)}"
            )
    return devices


class BleHandSensorSource:
    def __init__(
        self,
        config_path: Path,
        hands: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.config_path = config_path
        # None keeps the training collector's existing both-hands behavior.
        # Formal assessment passes its explicitly requested hands, currently
        # {"L"}; when a right-hand model is ready it can pass {"L", "R"}
        # without any BLE protocol or storage changes.
        self.hands = hands

    async def run(self, stop_event: asyncio.Event, on_packet: PacketHandler) -> None:
        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise RuntimeError("Install bleak on the Raspberry Pi to use BLE mode") from exc

        devices = load_devices(self.config_path, self.hands)
        connect_lock = asyncio.Lock()
        tasks = []

        for index, device in enumerate(devices):
            tasks.append(
                asyncio.create_task(
                    self._connect_device(
                        BleakClient,
                        device,
                        stop_event,
                        on_packet,
                        connect_lock,
                        startup_delay_seconds=index * CONNECT_ATTEMPT_GAP_SECONDS,
                    )
                )
            )

        await asyncio.gather(*tasks)

    async def _connect_device(
        self,
        bleak_client_cls,
        device: dict[str, str],
        stop_event: asyncio.Event,
        on_packet: PacketHandler,
        connect_lock: asyncio.Lock,
        startup_delay_seconds: float = 0,
    ) -> None:
        name = device["name"]
        address = device["address"]
        hand = device["hand"].upper()

        if startup_delay_seconds > 0:
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=startup_delay_seconds,
                )
                return
            except asyncio.TimeoutError:
                pass

        attempt = 0
        while not stop_event.is_set():
            attempt += 1
            receive_buffer = ""

            def on_data(_sender, data: bytearray) -> None:
                nonlocal receive_buffer
                receive_buffer += bytes(data).decode("utf-8", errors="replace")
                while "\n" in receive_buffer:
                    line, receive_buffer = receive_buffer.split("\n", 1)
                    line = line.rstrip("\r")
                    if line.startswith("SENSORS_OK,"):
                        print(f"[{name}] {line}")
                        continue
                    if line.startswith("SENSOR_ERROR,"):
                        print(f"[{name}] warning: {line}; continuing acquisition")
                        continue
                    packet = parse_hand_sensor_packet(
                        line,
                        received_at_unix_ms=time.time_ns() // 1_000_000,
                    )
                    if packet is not None:
                        asyncio.create_task(on_packet(packet))
                    else:
                        field_count = len(line.split(","))
                        preview = line if len(line) <= 180 else line[:177] + "..."
                        print(
                            f"[{name}] skipped invalid packet "
                            f"(fields={field_count}, chars={len(line)}): {preview!r}"
                        )

            try:
                print(f"[{name}] waiting for BLE connection slot")

                async with connect_lock:
                    if stop_event.is_set():
                        return

                    print(f"[{name}] connecting to {address} (attempt {attempt})")
                    client = bleak_client_cls(address, timeout=CONNECT_TIMEOUT_SECONDS)
                    await client.connect()

                try:
                    if not client.is_connected:
                        raise ConnectionError("BLE connection was not established")

                    print(f"[{name}] connected to {address}")

                    service = client.services.get_service(UART_SERVICE_UUID)
                    if service is None:
                        print(f"[{name}] UART service was not listed; trying characteristics directly")

                    await client.start_notify(UART_TX_UUID, on_data)
                    print(f"[{name}] UART notifications enabled")

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
                        try:
                            await client.write_gatt_char(UART_RX_UUID, b"STOP\n", response=False)
                        finally:
                            await client.stop_notify(UART_TX_UUID)

                finally:
                    if client.is_connected:
                        await client.disconnect()
            except Exception as error:
                print(f"[{name}] BLE error: {type(error).__name__}: {error!r}")

            if not stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=RECONNECT_DELAY_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass
