"""Realtime posture-to-voice feedback for guided piano practice.

The posture classifier produces a prediction for nearly every incoming IMU
packet.  Speaking every non-normal prediction would be distracting, so this
module requires a short stable streak and enforces a global cooldown before it
emits a browser-playable feedback event.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time


@dataclass(frozen=True)
class PostureCue:
    cue_id: str
    message: str
    audio_src: str


POSTURE_CUES: dict[str, PostureCue] = {
    "finger_collapse": PostureCue(
        cue_id="curve_fingers",
        message="Keep your fingers gently curved.",
        audio_src="/audio/posture/curve-fingers.wav",
    ),
    "high_lift_tap": PostureCue(
        cue_id="fingers_close",
        message="Keep your fingers close to the keys.",
        audio_src="/audio/posture/fingers-close.wav",
    ),
    "wrist_arch": PostureCue(
        cue_id="lower_wrist",
        message="Lower your wrist and keep it relaxed.",
        audio_src="/audio/posture/lower-wrist.wav",
    ),
    "wrist_collapse": PostureCue(
        cue_id="neutral_wrist",
        message="Lift your wrist into a neutral position.",
        audio_src="/audio/posture/neutral-wrist.wav",
    ),
    "wrist_shake": PostureCue(
        cue_id="steady_wrist",
        message="Steady your wrist and relax your hand.",
        audio_src="/audio/posture/steady-wrist.wav",
    ),
}


class PostureFeedbackGate:
    """Turn stable, confident posture predictions into sparse voice cues."""

    def __init__(
        self,
        *,
        minimum_confidence: float = 0.65,
        consecutive_predictions: int = 4,
        cooldown_seconds: float = 10.0,
    ) -> None:
        if consecutive_predictions < 1:
            raise ValueError("consecutive_predictions must be at least 1")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds cannot be negative")
        self.minimum_confidence = minimum_confidence
        self.consecutive_predictions = consecutive_predictions
        self.cooldown_seconds = cooldown_seconds
        self._streaks: dict[str, tuple[str, int]] = {}
        self._last_emitted_at: float | None = None

    def observe(
        self,
        *,
        hand: str,
        label: str,
        confidence: float,
        monotonic_now: float | None = None,
        unix_ms_now: int | None = None,
    ) -> dict | None:
        """Return an event only after a persistent actionable prediction."""
        normalized_hand = hand.upper()
        cue = POSTURE_CUES.get(label)
        if cue is None or confidence < self.minimum_confidence:
            self._streaks.pop(normalized_hand, None)
            return None

        previous_label, previous_count = self._streaks.get(
            normalized_hand, ("", 0)
        )
        streak_count = previous_count + 1 if previous_label == label else 1
        self._streaks[normalized_hand] = (label, streak_count)
        if streak_count < self.consecutive_predictions:
            return None

        now = time.monotonic() if monotonic_now is None else monotonic_now
        if (
            self._last_emitted_at is not None
            and now - self._last_emitted_at < self.cooldown_seconds
        ):
            return None

        created_at_unix_ms = (
            time.time_ns() // 1_000_000
            if unix_ms_now is None
            else unix_ms_now
        )
        self._last_emitted_at = now
        self._streaks[normalized_hand] = (label, 0)
        return {
            "schema_version": "posture_feedback_event_v1",
            "event_id": (
                f"{created_at_unix_ms}-{normalized_hand}-{cue.cue_id}"
            ),
            "created_at_unix_ms": created_at_unix_ms,
            "hand": normalized_hand,
            "label": label,
            "confidence": round(float(confidence), 4),
            "cue_id": cue.cue_id,
            "message": cue.message,
            "audio_src": cue.audio_src,
        }


def write_posture_feedback_event(output_path: Path, event: dict) -> None:
    """Atomically publish the latest event for the practice-session API."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f"{output_path.name}.tmp")
    temporary.write_text(
        json.dumps(event, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(output_path)
