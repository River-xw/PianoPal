#!/usr/bin/env python3
"""Steps through each of the 22 keys ONE LED at a time (the key's first LED
index in edge/led_key_mapping.json), one key at a time in C3->C6 order, for
manual visual verification against the physical keys -- the original
one-key-one-LED, one-at-a-time style, now using the corrected LED direction
(index 0 = LED1 = C6 end, confirmed by the red/blue test).

Run:
    python3 edge/ws2812_single_led_sequence.py
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step through each key's first LED, one at a time.")
    parser.add_argument("--color", default="0,255,0", help="R,G,B (0-255 each).")
    parser.add_argument("--brightness", type=float, default=0.2, help="0.0-1.0.")
    parser.add_argument("--hold-sec", type=float, default=1.0, help="How long each LED stays lit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    r, g, b = (int(v) for v in args.color.split(","))
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    keys = mapping["keys"]

    driver = WS2812SpiDriver(spi_bus=SPI_BUS, spi_device=SPI_DEVICE, led_count=mapping["strip_led_count"])
    strip = driver.get_strip()
    strip.set_brightness(args.brightness)

    for key in keys:
        led_1based = key["led_range_1based"][0]
        led_0based = led_1based - 1
        strip.clear()
        strip.set_pixel_color(led_0based, Color(r, g, b))
        strip.show()
        print(f"{key['name']:4s} (midi {key['midi']}) -> LED {led_1based}")
        time.sleep(args.hold_sec)

    strip.clear()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
