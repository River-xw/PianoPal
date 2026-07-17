"""Tunable settings for the camera_evidence module, in one place."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet


@dataclass
class CameraEvidenceConfig:
    # which scoring statuses trigger a camera lookup at all
    trigger_statuses: FrozenSet[str] = field(default_factory=lambda: frozenset({"wrong_pitch", "missed"}))

    # calibration / key-layout geometry
    black_key_width_ratio: float = 0.6    # black key width as a fraction of a white key's width
    black_key_depth_ratio: float = 0.62   # fraction of key depth (from the back) black keys physically reach
    calibration_edge_tolerance_px: float = 15.0  # forgive a fingertip reading this many px past the calibrated edge

    # SyntheticFingertipSource
    synthetic_lookup_tolerance_sec: float = 0.3  # max distance from a ref note's onset a query can still match it
