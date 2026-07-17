"""Fingertip position source abstraction, so the real camera implementation
can be swapped in later without changing any downstream cross-validation
logic. Camera doesn't detect press/no-press (onset timing stays with
audio/IMU) -- it only answers "at this timestamp, which key was the
fingertip over", a pure spatial lookup.
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Optional

from .calibration import pitch_to_pixel
from .config import CameraEvidenceConfig


class FingertipSource(ABC):
    @abstractmethod
    def get_position(self, timestamp_sec: float) -> Optional[tuple]:
        """Returns the (x, y) pixel position of the fingertip at (or nearest
        to) `timestamp_sec`, or None if no reading is available.
        """


class SyntheticFingertipSource(FingertipSource):
    """Fakes a fingertip trajectory from a reference.json: at each ref
    note's onset, the "finger" is over that note's correct key (converted
    through calibration), with configurable pixel noise and an injected
    wrong-key rate to simulate real detector misdetection. For testing until
    real camera hardware exists -- see MediaPipeFingertipSource below for
    the eventual real implementation.
    """

    def __init__(
        self,
        reference: dict,
        calibration: dict,
        noise_px: float = 5.0,
        error_rate: float = 0.0,
        config: Optional[CameraEvidenceConfig] = None,
        seed: Optional[int] = None,
    ):
        self.calibration = calibration
        self.noise_px = noise_px
        self.error_rate = error_rate
        self.config = config or CameraEvidenceConfig()
        self._rng = random.Random(seed)
        self._events = sorted(
            ((note["onset_sec"], note["pitch"]) for note in reference["notes"]),
            key=lambda event: event[0],
        )
        self._all_pitches = [k["pitch"] for k in calibration["white_keys"]] + [
            k["pitch"] for k in calibration["black_keys"]
        ]

    def get_position(self, timestamp_sec: float) -> Optional[tuple]:
        if not self._events:
            return None
        onset, pitch = min(self._events, key=lambda event: abs(event[0] - timestamp_sec))
        if abs(onset - timestamp_sec) > self.config.synthetic_lookup_tolerance_sec:
            return None

        target_pitch = pitch
        if self.error_rate > 0 and self._rng.random() < self.error_rate:
            candidates = [p for p in self._all_pitches if p != pitch]
            if candidates:
                target_pitch = self._rng.choice(candidates)

        position = pitch_to_pixel(target_pitch, self.calibration)
        if position is None:
            return None
        x, y = position
        x += self._rng.gauss(0.0, self.noise_px)
        y += self._rng.gauss(0.0, self.noise_px)
        return (x, y)


class MediaPipeFingertipSource(FingertipSource):
    """Real camera implementation -- NOT implemented yet, since there's no
    camera hardware to build or test against.

    TODO (once camera hardware is available): open the camera/video stream,
    run MediaPipe Hands per frame, track the index fingertip landmark (or
    whichever landmark best approximates the "playing" fingertip), buffer
    (timestamp, x, y) readings, and answer get_position() by returning the
    buffered reading nearest `timestamp_sec` (or briefly interpolating
    between the two closest frames if timestamps don't land exactly on a
    captured frame).
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "MediaPipeFingertipSource is not implemented yet -- no camera hardware "
            "available to build or test against. Use SyntheticFingertipSource until then."
        )

    def get_position(self, timestamp_sec: float) -> Optional[tuple]:
        raise NotImplementedError("MediaPipeFingertipSource is not implemented yet.")
