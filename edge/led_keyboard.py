"""Shared helper: the physical WS2812 strip along the BF-3738C keyboard, plus
the pitch -> LED-indices mapping (edge/led_key_mapping.json).

Reused by the LED test scripts and by the song-guidance / scoring-feedback
tools, so the "which LEDs belong to which key" fact lives in exactly one
place (the JSON) and the driver wiring (Pi 5 SPI, GPIO10) in exactly one
place (here).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from rpi5_ws2812.ws2812 import Color, Strip, WS2812SpiDriver

SPI_BUS = 0
SPI_DEVICE = 0  # /dev/spidev0.0 -- SPI0 CE0, MOSI on GPIO10 (physical pin 19)
MAPPING_PATH = Path(__file__).resolve().parent / "led_key_mapping.json"


def load_mapping(path: Optional[Path] = None) -> dict:
    return json.loads((path or MAPPING_PATH).read_text(encoding="utf-8"))


def pitch_to_leds(mapping: dict) -> dict[int, list[int]]:
    """MIDI pitch -> list of 0-based LED indices for that key."""
    return {int(k["midi"]): list(k["led_indices_0based"]) for k in mapping["keys"]}


def make_strip(mapping: dict, brightness: float = 0.2) -> Strip:
    driver = WS2812SpiDriver(spi_bus=SPI_BUS, spi_device=SPI_DEVICE, led_count=mapping["strip_led_count"])
    strip = driver.get_strip()
    strip.set_brightness(brightness)
    return strip
