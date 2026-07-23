#!/usr/bin/env python3
"""Runs the hand-posture IMU pipeline (BLE micro:bit + MPU6050, teammate's
edge/raspi_runtime/posture.py & ble.py) for the duration of a practice
session, and writes an aggregate hand_shape_score once stopped.

Unlike ws2812_guide_song.py (which ends on its own once the song finishes),
this has no natural end -- it runs until edge/practice_server.py sends it
SIGTERM at the end of a session, same lifecycle as the audio recording.

Graceful degradation is the whole point: if --ble-config is missing, or the
BLE connection/bleak import fails, this writes a null-score result instead
of raising, so hand-shape posture sensing is fully optional hardware, not a
requirement to practice -- edge/practice_server.py falls back to its fixed
placeholder score whenever hand_shape_score comes back null.

Run:
    python3 edge/posture_capture.py --ble-config edge/microbit_rpi_comm/raspberry/config.json \\
        --posture-model models/gesture/left_hand_posture_classifier.joblib -o posture_result.json
    python3 edge/posture_capture.py -o posture_result.json   # no --ble-config -> immediate null result
"""
from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from edge.raspi_runtime.ble import BleHandSensorSource  # noqa: E402
from edge.raspi_runtime.posture import RealtimePosturePipeline, load_posture_model  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture+classify hand posture over BLE for one practice session.")
    parser.add_argument("--ble-config", type=Path, default=None,
                        help="edge/microbit_rpi_comm/raspberry/config.json -- omit to skip posture sensing entirely.")
    parser.add_argument("--posture-model", type=Path, default=None,
                        help="Trained .joblib/.json posture model (see edge/raspi_runtime/posture.py's load_posture_model).")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Where to write the aggregate result JSON.")
    return parser.parse_args()


def _write_result(output_path: Path, total: int, normal: int, label_counts: dict[str, int], error: str | None = None) -> None:
    score = round(normal / total * 100, 2) if total > 0 else None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "hand_shape_score": score,
        "total_predictions": total,
        "normal_predictions": normal,
        "label_counts": label_counts,
        "error": error,
    }), encoding="utf-8")


async def _run(args: argparse.Namespace) -> None:
    if args.ble_config is None or not args.ble_config.exists():
        _write_result(args.output, 0, 0, {}, error="no --ble-config given, hand-shape posture sensing skipped")
        return

    # Mirrors edge/raspi_runtime/session.py's window_ms choice: a real
    # trained model gets a wider window than the threshold baseline.
    model = load_posture_model(args.posture_model)
    pipeline = RealtimePosturePipeline(model=model, window_ms=2000 if args.posture_model is not None else 800)

    total = 0
    normal = 0
    label_counts: dict[str, int] = {}
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    async def handle_packet(packet) -> None:
        nonlocal total, normal
        prediction = pipeline.add_packet(packet)
        if prediction is None:
            return
        total += 1
        label_counts[prediction.predicted_label] = label_counts.get(prediction.predicted_label, 0) + 1
        if prediction.predicted_label == "normal":
            normal += 1

    try:
        await BleHandSensorSource(args.ble_config).run(stop_event, handle_packet)
    except Exception as exc:  # bleak not installed, connection failure, etc. -- degrade, don't crash
        _write_result(args.output, total, normal, label_counts, error=str(exc))
        return

    _write_result(args.output, total, normal, label_counts)


def main() -> int:
    args = parse_args()
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
