#!/usr/bin/env python3
"""Lights all 22 keys' LED ranges at once (not one-at-a-time), each key in a
distinct color spread evenly around the color wheel so adjacent keys'
boundaries are visually obvious, using edge/led_key_mapping.json.

Run:
    python3 edge/ws2812_key_mapping_test.py
    python3 edge/ws2812_key_mapping_test.py --brightness 0.1 --seconds 10
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from rpi5_ws2812.ws2812 import Color, WS2812SpiDriver

SPI_BUS = 0
SPI_DEVICE = 0  # /dev/spidev0.0 -- SPI0 CE0, MOSI on GPIO10
MAPPING_PATH = Path(__file__).resolve().parent / "led_key_mapping.json"


def wheel(pos: int) -> Color:
    """Standard NeoPixel color wheel: pos 0-255 -> a color around the hue circle."""
    pos = pos % 256
    if pos < 85:
        return Color(255 - pos * 3, pos * 3, 0)
    if pos < 170:
        pos -= 85
        return Color(0, 255 - pos * 3, pos * 3)
    pos -= 170
    return Color(pos * 3, 0, 255 - pos * 3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Light all 22 keys' LED ranges at once, in distinct colors.")
    parser.add_argument("--brightness", type=float, default=0.15, help="0.0-1.0, default dim (0.15).")
    parser.add_argument("--seconds", type=float, default=None, help="How long to stay lit (default: until Ctrl+C).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    keys = mapping["keys"]

    driver = WS2812SpiDriver(spi_bus=SPI_BUS, spi_device=SPI_DEVICE, led_count=mapping["strip_led_count"])
    strip = driver.get_strip()
    strip.set_brightness(args.brightness)

    # Consecutive hue-wheel positions (i*256/22) look like a smooth rainbow --
    # adjacent keys end up close in hue and hard to tell apart by eye. Jump
    # around the wheel by the golden angle each step instead, so neighboring
    # keys always land far apart in hue while still covering the full wheel.
    golden_ratio_conjugate = 0.618034
    for i, key in enumerate(keys):
        color = wheel(int((i * golden_ratio_conjugate * 256)) % 256)
        for idx in key["led_indices_0based"]:
            strip.set_pixel_color(idx, color)
        print(f"{key['name']:4s} (midi {key['midi']}) -> LEDs {key['led_range_1based']}  color={tuple(color)}")
    strip.show()

    try:
        if args.seconds is None:
            print("lit -- Ctrl+C to turn off")
            while True:
                time.sleep(1)
        else:
            time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        strip.clear()
        print("off")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
