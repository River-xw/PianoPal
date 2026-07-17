#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import signal
from pathlib import Path
from typing import Any

from bleak import BleakClient


# micro:bit Bluetooth UART Service
UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"

# micro:bit -> Raspberry Pi
# Raspberry Pi listens for notifications from this characteristic.
UART_TX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

# Raspberry Pi -> micro:bit
# Raspberry Pi writes commands to this characteristic.
UART_RX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


CONFIG_PATH = Path("config.json")

RECONNECT_DELAY_SECONDS = 5
CONNECT_TIMEOUT_SECONDS = 20
COMMAND_DELAY_SECONDS = 0.5


def parse_message(
    device_name: str,
    line: str,
) -> dict[str, int | str] | None:
    """
    Parse one complete line received from a micro:bit.

    Supported messages:

        READY
        STARTED LEFT
        STARTED RIGHT
        STOPPED
        DATA,left,t,ax,ay,az
        DATA,right,t,ax,ay,az
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

    parts = line.split(",")

    if len(parts) != 6:
        print(f"[{device_name}] Unknown message: {line}")
        return None

    packet_type, hand, t_text, ax_text, ay_text, az_text = parts

    if packet_type != "DATA":
        print(f"[{device_name}] Unknown packet type: {packet_type}")
        return None

    hand = hand.lower()

    if hand not in {"left", "right"}:
        print(f"[{device_name}] Invalid hand value: {hand}")
        return None

    try:
        packet: dict[str, int | str] = {
            "device": device_name,
            "hand": hand,
            "t": int(t_text),
            "ax": int(ax_text),
            "ay": int(ay_text),
            "az": int(az_text),
        }
    except ValueError:
        print(f"[{device_name}] Invalid numeric data: {line}")
        return None

    return packet


def print_packet(packet: dict[str, int | str]) -> None:
    """Print one parsed acceleration packet."""

    print(
        f"[{packet['device']}] "
        f"hand={packet['hand']} "
        f"t={packet['t']} ms "
        f"ax={packet['ax']} mg "
        f"ay={packet['ay']} mg "
        f"az={packet['az']} mg"
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
                    print_packet(packet)

        try:
            print(f"[{device_name}] Connecting to {address}...")

            async with BleakClient(
                address,
                timeout=CONNECT_TIMEOUT_SECONDS,
            ) as client:
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

    tasks = [
        asyncio.create_task(
            connect_microbit(
                device_name=device["name"],
                address=device["address"],
                hand=device["hand"],
                stop_event=stop_event,
            ),
            name=device["name"],
        )
        for device in devices
    ]

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