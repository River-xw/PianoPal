#!/usr/bin/env python3
"""Runs the hand-posture IMU pipeline (BLE micro:bit + MPU6050, teammate's
edge/raspi_runtime/posture.py & ble.py) for the duration of a practice
session, and writes an aggregate hand_shape_score once stopped.

Unlike ws2812_guide_song.py (which ends on its own once the song finishes),
this has no natural end -- it runs until edge/practice_server.py sends it
SIGTERM at the end of a session, same lifecycle as the audio recording.

Graceful degradation is the whole point: if --ble-config is missing, or the
BLE connection/bleak import fails, this writes a null-score result instead
of raising, so motion sensing is optional hardware rather than a requirement
to practice. edge/practice_server.py leaves the motion score unavailable and
renormalizes the remaining audio scores; it never substitutes a fake score.

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
import time
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
    parser.add_argument(
        "--hands",
        nargs="+",
        choices=["L", "R"],
        default=["L"],
        help="Hands to include in the formal motion score. The current trained model is left-hand only.",
    )
    parser.add_argument(
        "--start-delay-sec",
        type=float,
        default=0.0,
        help="Warm up BLE/model buffering immediately, but only count predictions after this delay.",
    )
    parser.add_argument("-o", "--output", type=Path, required=True, help="Where to write the aggregate result JSON.")
    return parser.parse_args()


def _write_result(
    output_path: Path,
    total: int,
    normal: int,
    label_counts: dict[str, int],
    *,
    capture_hands: list[str],
    model_name: str | None = None,
    model_version: str | None = None,
    error: str | None = None,
) -> None:
    score = round(normal / total * 100, 2) if total > 0 else None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "schema_version": "formal_motion_assessment_v1",
        "available": score is not None,
        "hand_shape_score": score,
        "motion_score": score,
        "total_predictions": total,
        "normal_predictions": normal,
        "label_counts": label_counts,
        "capture_hands": capture_hands,
        "model_name": model_name,
        "model_version": model_version,
        "score_formula": "normal_predictions / total_predictions * 100",
        "error": error,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


async def _run(args: argparse.Namespace) -> None:
    capture_hands = sorted(set(args.hands))
    if args.ble_config is None or not args.ble_config.exists():
        _write_result(
            args.output,
            0,
            0,
            {},
            capture_hands=capture_hands,
            error="BLE configuration unavailable; motion recognition skipped",
        )
        return

    # Mirrors edge/raspi_runtime/session.py's window_ms choice: a real
    # trained model gets a wider window than the threshold baseline.
    try:
        model = load_posture_model(args.posture_model)
    except Exception as exc:
        _write_result(
            args.output,
            0,
            0,
            {},
            capture_hands=capture_hands,
            error=f"could not load motion model: {exc}",
        )
        return
    pipeline = RealtimePosturePipeline(model=model, window_ms=2000 if args.posture_model is not None else 800)

    total = 0
    normal = 0
    label_counts: dict[str, int] = {}
    stop_event = asyncio.Event()
    scoring_starts_at = time.monotonic() + max(0.0, float(args.start_delay_sec))

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    async def handle_packet(packet) -> None:
        nonlocal total, normal
        if packet.hand not in capture_hands:
            return
        prediction = pipeline.add_packet(packet)
        # Feed the rolling model window during the guide's lead-in so motion
        # inference is warm when microphone recording starts, but do not let
        # countdown/setup movements affect the formal performance score.
        if prediction is None or time.monotonic() < scoring_starts_at:
            return
        total += 1
        label_counts[prediction.predicted_label] = label_counts.get(prediction.predicted_label, 0) + 1
        if prediction.predicted_label == "normal":
            normal += 1

    try:
        await BleHandSensorSource(args.ble_config).run(stop_event, handle_packet)
    except Exception as exc:  # bleak not installed, connection failure, etc. -- degrade, don't crash
        _write_result(
            args.output,
            total,
            normal,
            label_counts,
            capture_hands=capture_hands,
            model_name=model.model_name,
            model_version=model.model_version,
            error=str(exc),
        )
        return

    _write_result(
        args.output,
        total,
        normal,
        label_counts,
        capture_hands=capture_hands,
        model_name=model.model_name,
        model_version=model.model_version,
    )


def main() -> int:
    args = parse_args()
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
