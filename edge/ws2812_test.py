#!/usr/bin/env python3
"""Minimal WS2812 bring-up test -- lights the strip solid white, waits, then
turns it off. Run this directly on the Raspberry Pi (not on the dev machine).

Raspberry Pi 5 note: the classic rpi_ws281x library drives WS2812 via
PWM+DMA register addresses that don't exist on Pi 5's new RP1 I/O chip
(ws2811_init fails with "Hardware revision is not supported"). This uses
rpi5-ws2812 instead, which bit-bangs the WS2812 protocol over SPI.

Wiring: WS2812 data-in -> GPIO10 (physical pin 19, SPI0 MOSI), not GPIO18 --
GPIO18's PWM peripheral is what's unsupported on Pi 5, not the pin itself.

Install (on the Pi):
    sudo pip3 install rpi5-ws2812 --break-system-packages

SPI must be enabled (dtparam=spi=on in /boot/firmware/config.txt, reboot
after changing it) -- /dev/spidev0.0 must exist.

Run:
    python3 edge/ws2812_test.py --count 8
"""
from __future__ import annotations

import argparse
import time

from rpi5_ws2812.ws2812 import Color, WS2812SpiDriver

SPI_BUS = 0
SPI_DEVICE = 0  # /dev/spidev0.0 -- SPI0 CE0, MOSI on GPIO10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Light up a WS2812 strip on GPIO10 (SPI0 MOSI).")
    parser.add_argument("--count", type=int, default=8, help="Number of LEDs on the strip.")
    parser.add_argument("--color", default="255,255,255", help="R,G,B (0-255 each).")
    parser.add_argument("--seconds", type=float, default=5.0, help="How long to stay lit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    r, g, b = (int(v) for v in args.color.split(","))

    driver = WS2812SpiDriver(spi_bus=SPI_BUS, spi_device=SPI_DEVICE, led_count=args.count)
    strip = driver.get_strip()

    color = Color(r, g, b)
    strip.set_all_pixels(color)
    strip.show()
    print(f"lit {strip.num_pixels()} pixel(s) with RGB({r},{g},{b}) -- holding for {args.seconds}s")

    time.sleep(args.seconds)

    strip.clear()
    print("off")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
