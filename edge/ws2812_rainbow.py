#!/usr/bin/env python3
"""Rainbow-cycle animation for a WS2812 strip on a Raspberry Pi 5 (SPI driver,
see edge/ws2812_test.py for why -- the classic PWM library doesn't work on
Pi 5's RP1 I/O chip). Spreads the color wheel across the strip's length and
rotates the phase over time, so a full rainbow flows continuously along it.

Wiring: WS2812 data-in -> GPIO10 (physical pin 19, SPI0 MOSI).

Run:
    python3 edge/ws2812_rainbow.py --count 51
    (Ctrl+C to stop -- turns the strip off on the way out.)
"""
from __future__ import annotations

import argparse
import time

from rpi5_ws2812.ws2812 import Color, WS2812SpiDriver

SPI_BUS = 0
SPI_DEVICE = 0  # /dev/spidev0.0 -- SPI0 CE0, MOSI on GPIO10


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
    parser = argparse.ArgumentParser(description="Rainbow-cycle a WS2812 strip on GPIO10 (SPI0 MOSI).")
    parser.add_argument("--count", type=int, default=51, help="Number of LEDs on the strip.")
    parser.add_argument("--seconds", type=float, default=None, help="Run this long, then stop (default: run until Ctrl+C).")
    parser.add_argument("--speed", type=float, default=2.0, help="Full wheel rotations per second.")
    parser.add_argument("--frame-delay", type=float, default=0.02, help="Seconds between frames (~50 FPS default).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    driver = WS2812SpiDriver(spi_bus=SPI_BUS, spi_device=SPI_DEVICE, led_count=args.count)
    strip = driver.get_strip()
    n = strip.num_pixels()

    start = time.monotonic()
    phase = 0
    try:
        while args.seconds is None or (time.monotonic() - start) < args.seconds:
            for i in range(n):
                strip.set_pixel_color(i, wheel(int(i * 256 / n) + phase))
            strip.show()
            phase = (phase + int(256 * args.speed * args.frame_delay)) % 256
            time.sleep(args.frame_delay)
    except KeyboardInterrupt:
        pass
    finally:
        strip.clear()
        print("off")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
