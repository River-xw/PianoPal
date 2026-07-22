#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

from bleak import BleakClient

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.sensors import RawHandSensorPacket, parse_hand_sensor_packet


# micro:bit Bluetooth UART Service
UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"

# micro:bit -> Raspberry Pi
# Raspberry Pi listens for notifications from this characteristic.
UART_TX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

# Raspberry Pi -> micro:bit
# Raspberry Pi writes commands to this characteristic.
UART_RX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


CONFIG_PATH = Path(__file__).resolve().with_name("config.json")

RECONNECT_DELAY_SECONDS = 5
CONNECT_TIMEOUT_SECONDS = 20
COMMAND_DELAY_SECONDS = 0.5
CONNECT_ATTEMPT_GAP_SECONDS = 2


def parse_message(
    device_name: str,
    line: str,
) -> RawHandSensorPacket | None:
    """
    Parse one complete line received from a micro:bit.

    Supported messages:

        READY
        STARTED LEFT
        STARTED RIGHT
        STOPPED
        L,seq,timestamp_ms,tip_ax,tip_ay,tip_az,tip_gx,tip_gy,tip_gz,
          back_ax,back_ay,back_az,back_gx,back_gy,back_gz,
          wrist_ax,wrist_ay,wrist_az
        R,seq,timestamp_ms,tip_ax,tip_ay,tip_az,tip_gx,tip_gy,tip_gz,
          back_ax,back_ay,back_az,back_gx,back_gy,back_gz,
          wrist_ax,wrist_ay,wrist_az
    """

    line = line.strip()

    if not line:
        return None

    if line == "READY":
        print(f"[{device_name}] micro:bit is ready")
        return None

    if line == "STARTED LEFT":
        print(f"[{device_name}] left-hand data streaming started")
        return None

    if line == "STARTED RIGHT":
        print(f"[{device_name}] right-hand data streaming started")
        return None

    if line == "STOPPED":
        print(f"[{device_name}] data streaming stopped")
        return None

    received_at_unix_ms = time.time_ns() // 1_000_000
    packet = parse_hand_sensor_packet(
        line,
        received_at_unix_ms=received_at_unix_ms,
    )

    if packet is None:
        print(f"[{device_name}] Skipped invalid packet")

    return packet


def print_packet(device_name: str, packet: RawHandSensorPacket) -> None:
    """Print one parsed aggregate hand sensor packet."""

    fingertip_gyro_y = packet.fingertip.gyro.y if packet.fingertip.gyro else None
    hand_back_gyro_z = packet.hand_back.gyro.z if packet.hand_back.gyro else None

    def format_optional(value: float | None) -> str:
        return "NA" if value is None else f"{value:g}"

    print(
        f"[{device_name}] "
        f"hand={packet.hand} "
        f"seq={packet.sequence_number} "
        f"t={packet.device_timestamp_ms} ms "
        f"tip_ax={packet.fingertip.accel.x:g} "
        f"tip_gy={format_optional(fingertip_gyro_y)} "
        f"back_gz={format_optional(hand_back_gyro_z)} "
        f"wrist_az={packet.wrist.accel.z:g}"
    )


async def send_command(
    client: BleakClient,
    device_name: str,
    command: str,
) -> None:
    """Send one newline-terminated command to a micro:bit."""

    payload = f"{command}\n".encode("utf-8")

    await client.write_gatt_char(
        UART_RX_UUID,
        payload,
        response=False,
    )

    print(f"[{device_name}] Sent: {command}")


async def connect_microbit(
    device_name: str,
    address: str,
    hand: str,
    stop_event: asyncio.Event,
    connect_lock: asyncio.Lock,
    startup_delay_seconds: float = 0,
) -> None:
    """
    Connect to one micro:bit and receive acceleration data.

    The function reconnects automatically if the BLE connection is lost.
    """

    hand = hand.lower()

    if hand not in {"left", "right"}:
        raise ValueError(
            f'Invalid hand "{hand}" for {device_name}. '
            'Expected "left" or "right".'
        )

    if startup_delay_seconds > 0:
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=startup_delay_seconds,
            )
            return
        except asyncio.TimeoutError:
            pass

    while not stop_event.is_set():
        receive_buffer = ""

        def on_data(_sender: Any, data: bytearray) -> None:
            """
            Handle BLE UART notifications.

            One BLE notification may contain:
            - part of one line;
            - exactly one line;
            - multiple lines.

            Therefore, received text is stored in a buffer and split by '\\n'.
            """

            nonlocal receive_buffer

            chunk = bytes(data).decode(
                "utf-8",
                errors="replace",
            )

            receive_buffer += chunk

            while "\n" in receive_buffer:
                line, receive_buffer = receive_buffer.split("\n", 1)

                # Remove a possible carriage return from \r\n.
                line = line.rstrip("\r")

                packet = parse_message(
                    device_name=device_name,
                    line=line,
                )

                if packet is not None:
                    print_packet(device_name, packet)

        try:
            print(f"[{device_name}] Waiting for BLE connection slot...")

            async with connect_lock:
                if stop_event.is_set():
                    return

                print(f"[{device_name}] Connecting to {address}...")

                client = BleakClient(
                    address,
                    timeout=CONNECT_TIMEOUT_SECONDS,
                )

                await client.connect()

            try:
                if not client.is_connected:
                    raise ConnectionError("BLE connection was not established")

                print(f"[{device_name}] Connected to {address}")

                # Optional check: confirm that the UART service exists.
                uart_service = client.services.get_service(
                    UART_SERVICE_UUID
                )

                if uart_service is None:
                    raise RuntimeError(
                        "micro:bit UART service was not found. "
                        "Check that bluetooth.startUartService() "
                        "is present in MakeCode."
                    )

                await client.start_notify(
                    UART_TX_UUID,
                    on_data,
                )

                print(f"[{device_name}] UART notifications enabled")

                # Application-level handshake.
                await send_command(
                    client,
                    device_name,
                    "CONNECT",
                )

                await asyncio.sleep(COMMAND_DELAY_SECONDS)

                # Only send the command for this configured device.
                await send_command(
                    client,
                    device_name,
                    f"START {hand.upper()}",
                )

                while client.is_connected and not stop_event.is_set():
                    await asyncio.sleep(0.5)

                if client.is_connected:
                    try:
                        await send_command(
                            client,
                            device_name,
                            "STOP",
                        )

                        await asyncio.sleep(0.2)
                    except Exception as error:
                        print(
                            f"[{device_name}] "
                            f"Could not send STOP: {error}"
                        )

                    try:
                        await client.stop_notify(UART_TX_UUID)
                    except Exception:
                        pass

                if not stop_event.is_set():
                    print(f"[{device_name}] Connection lost")

            finally:
                if client.is_connected:
                    await client.disconnect()

        except asyncio.CancelledError:
            raise

        except Exception as error:
            print(f"[{device_name}] Connection error: {error}")

        if not stop_event.is_set():
            print(
                f"[{device_name}] Retrying in "
                f"{RECONNECT_DELAY_SECONDS} seconds..."
            )

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=RECONNECT_DELAY_SECONDS,
                )
            except asyncio.TimeoutError:
                pass


def load_devices(config_path: Path) -> list[dict[str, str]]:
    """Load and validate micro:bit devices from config.json."""

    if not config_path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}"
        )

    try:
        config = json.loads(
            config_path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in {config_path}: {error}"
        ) from error

    devices = config.get("devices")

    if not isinstance(devices, list) or not devices:
        raise ValueError(
            'config.json must contain a non-empty "devices" list'
        )

    validated_devices: list[dict[str, str]] = []

    for index, device in enumerate(devices, start=1):
        if not isinstance(device, dict):
            raise ValueError(
                f"Device entry {index} must be a JSON object"
            )

        name = device.get("name")
        address = device.get("address")
        hand = device.get("hand")

        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f'Device entry {index} has an invalid "name"'
            )

        if not isinstance(address, str) or not address.strip():
            raise ValueError(
                f'Device entry {index} has an invalid "address"'
            )

        if not isinstance(hand, str):
            raise ValueError(
                f'Device entry {index} must contain '
                f'"hand": "left" or "right"'
            )

        hand = hand.lower().strip()

        if hand not in {"left", "right"}:
            raise ValueError(
                f'Device "{name}" has invalid hand "{hand}"'
            )

        validated_devices.append(
            {
                "name": name.strip(),
                "address": address.strip(),
                "hand": hand,
            }
        )

    return validated_devices


async def main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        if not stop_event.is_set():
            print("\nStopping...")
            stop_event.set()

    # Handle Ctrl+C and system termination.
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                signal_name,
                request_stop,
            )
        except NotImplementedError:
            pass

    try:
        devices = load_devices(CONFIG_PATH)
    except (FileNotFoundError, ValueError) as error:
        print(f"Configuration error: {error}")
        return

    print(f"Loaded {len(devices)} micro:bit device(s):")

    for device in devices:
        print(
            f"  {device['name']}: "
            f"{device['address']} "
            f"({device['hand']})"
        )

    connect_lock = asyncio.Lock()
    tasks = []

    for index, device in enumerate(devices):
        tasks.append(asyncio.create_task(
            connect_microbit(
                device_name=device["name"],
                address=device["address"],
                hand=device["hand"],
                stop_event=stop_event,
                connect_lock=connect_lock,
                startup_delay_seconds=index * CONNECT_ATTEMPT_GAP_SECONDS,
            ),
            name=device["name"],
        ))

    try:
        await stop_event.wait()
    finally:
        stop_event.set()

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *tasks,
                    return_exceptions=True,
                ),
                timeout=5,
            )
        except asyncio.TimeoutError:
            for task in tasks:
                task.cancel()

            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        print("Program stopped")


if __name__ == "__main__":
    asyncio.run(main())
