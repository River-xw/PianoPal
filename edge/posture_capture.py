#!/usr/bin/env python3
"""Runs the hand-posture IMU pipeline (BLE micro:bit + MPU6050, teammate's
edge/raspi_runtime/posture.py & ble.py) for the duration of a practice
session, and writes an aggregate hand_shape_score once stopped.

Unlike ws2812_guide_song.py (which ends on its own once the song finishes),
this has no natural end -- it runs until edge/practice_server.py sends it
SIGTERM at the end of a session, same lifecycle as the audio recording.

When used alone, missing configuration or a BLE/import failure is persisted as
a null-score result instead of raising. Formal scored sessions add a stricter
readiness gate in edge/practice_server.py: all requested hands must stream a
valid packet before the guide and microphone are allowed to start.

Run:
    python3 edge/posture_capture.py --ble-config edge/microbit_rpi_comm/raspberry/config.json \\
        --posture-model models/gesture/left_hand_posture_classifier.joblib -o posture_result.json
    python3 edge/posture_capture.py -o posture_result.json   # no --ble-config -> immediate null result
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
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
from edge.posture_feedback import (  # noqa: E402
    PostureFeedbackGate,
    write_posture_feedback_event,
)

BLE_SHUTDOWN_GRACE_SECONDS = 2.0


async def _run_source_until_stopped(
    source,
    stop_event: asyncio.Event,
    handle_packet,
    *,
    shutdown_grace_seconds: float = BLE_SHUTDOWN_GRACE_SECONDS,
) -> None:
    """Run one BLE source and make process shutdown bounded.

    Bleak connection attempts may remain inside the platform Bluetooth stack
    longer than practice_server waits for this process. Cancelling after a
    short grace period ensures the caller can still persist the aggregate
    motion result instead of being killed with no output file.
    """
    source_task = asyncio.create_task(source.run(stop_event, handle_packet))
    stopped_task = asyncio.create_task(stop_event.wait())
    try:
        done, _pending = await asyncio.wait(
            {source_task, stopped_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if source_task in done:
            await source_task
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(source_task),
                timeout=shutdown_grace_seconds,
            )
        except asyncio.TimeoutError:
            source_task.cancel()
            with suppress(asyncio.CancelledError):
                await source_task
    finally:
        stopped_task.cancel()
        with suppress(asyncio.CancelledError):
            await stopped_task


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
        help=(
            "Warm up BLE/model buffering immediately, but only count "
            "predictions this many seconds after all requested hands become ready."
        ),
    )
    parser.add_argument(
        "--ready-output",
        type=Path,
        default=None,
        help=(
            "Optional readiness JSON written after every requested hand has "
            "provided at least one valid sensor packet."
        ),
    )
    parser.add_argument(
        "--feedback-output",
        type=Path,
        default=None,
        help=(
            "Optional latest-event JSON used by the guided-practice UI to "
            "play sparse English posture reminders."
        ),
    )
    parser.add_argument("-o", "--output", type=Path, required=True, help="Where to write the aggregate result JSON.")
    return parser.parse_args()


def _write_ready(output_path: Path, capture_hands: list[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f"{output_path.name}.tmp")
    temporary.write_text(json.dumps({
        "schema_version": "formal_motion_ready_v1",
        "ready": True,
        "capture_hands": capture_hands,
        "ready_at_unix_ms": time.time_ns() // 1_000_000,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output_path)


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
    feedback_output = getattr(args, "feedback_output", None)
    if args.ready_output is not None:
        args.ready_output.unlink(missing_ok=True)
    if feedback_output is not None:
        feedback_output.unlink(missing_ok=True)
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
    feedback_gate = PostureFeedbackGate()

    total = 0
    normal = 0
    label_counts: dict[str, int] = {}
    stop_event = asyncio.Event()
    seen_hands: set[str] = set()
    scoring_starts_at: float | None = None

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    async def handle_packet(packet) -> None:
        nonlocal total, normal, scoring_starts_at
        if packet.hand not in capture_hands:
            return
        seen_hands.add(packet.hand)
        if scoring_starts_at is None and seen_hands.issuperset(capture_hands):
            # Readiness is based on real, parseable streaming data rather than
            # merely opening a BLE connection. Starting the score delay here
            # aligns it with practice_server launching the guide countdown
            # immediately after observing this readiness file.
            scoring_starts_at = (
                time.monotonic() + max(0.0, float(args.start_delay_sec))
            )
            if args.ready_output is not None:
                _write_ready(args.ready_output, capture_hands)
        prediction = pipeline.add_packet(packet)
        # Feed the rolling model window during the guide's lead-in so motion
        # inference is warm when microphone recording starts, but do not let
        # countdown/setup movements affect the formal performance score.
        if (
            prediction is None
            or scoring_starts_at is None
            or time.monotonic() < scoring_starts_at
        ):
            return
        total += 1
        label_counts[prediction.predicted_label] = label_counts.get(prediction.predicted_label, 0) + 1
        if prediction.predicted_label == "normal":
            normal += 1
        if feedback_output is not None:
            feedback_event = feedback_gate.observe(
                hand=prediction.hand,
                label=prediction.predicted_label,
                confidence=prediction.confidence,
            )
            if feedback_event is not None:
                write_posture_feedback_event(
                    feedback_output,
                    feedback_event,
                )

    source = BleHandSensorSource(args.ble_config, hands=frozenset(capture_hands))
    try:
        await _run_source_until_stopped(source, stop_event, handle_packet)
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
        error=(
            None
            if total > 0
            else f"no usable BLE predictions were received for hands {capture_hands}"
        ),
    )


def main() -> int:
    args = parse_args()
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
