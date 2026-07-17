"""Keyboard calibration: maps camera pixel coordinates to MIDI pitch.

One-time setup per camera placement -- given the pixel corners of the
visible key area (from a photo or a live frame) and the MIDI pitch range
they cover, this builds a perspective (homography) mapping from image pixels
to normalized keyboard space (u = left-to-right position across the pitch
range, v = front-to-back position on the keys), then lays out white keys as
evenly-spaced bands across u and black keys as narrower bands centered on
the boundary between the white keys they sit above -- the standard piano
layout (no black key between E-F or B-C), restricted to the front portion
(low v) of the keys since black keys don't reach the front edge.

The result is saved as plain JSON so it's redone only when the camera moves.
"""
from __future__ import annotations

import json
from typing import Optional

import numpy as np

from .config import CameraEvidenceConfig

WHITE_PITCH_CLASSES = {0, 2, 4, 5, 7, 9, 11}  # C D E F G A B


def is_white_key(pitch: int) -> bool:
    return pitch % 12 in WHITE_PITCH_CLASSES


def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _solve_homography(src_pts: list, dst_pts: list) -> np.ndarray:
    """DLT solve for the 3x3 homography H such that, in homogeneous
    coordinates, [u, v, 1] ~ H @ [x, y, 1] for each (x, y) <-> (u, v) pair.
    """
    rows = []
    for (x, y), (u, v) in zip(src_pts, dst_pts):
        rows.append([-x, -y, -1, 0, 0, 0, x * u, y * u, u])
        rows.append([0, 0, 0, -x, -y, -1, x * v, y * v, v])
    A = np.asarray(rows, dtype=float)
    _, _, Vt = np.linalg.svd(A)
    H = Vt[-1].reshape(3, 3)
    return H / H[2, 2]


def _apply_homography(H: np.ndarray, x: float, y: float) -> Optional[tuple]:
    vec = H @ np.array([x, y, 1.0])
    if abs(vec[2]) < 1e-12:
        return None
    return float(vec[0] / vec[2]), float(vec[1] / vec[2])


def _build_key_layout(lowest_pitch: int, highest_pitch: int, black_key_width_ratio: float):
    white_pitches = [p for p in range(lowest_pitch, highest_pitch + 1) if is_white_key(p)]
    if not white_pitches:
        raise ValueError("pitch range must include at least one white key")

    band_width = 1.0 / len(white_pitches)
    white_index = {p: i for i, p in enumerate(white_pitches)}
    white_keys = [
        {"pitch": p, "u_low": i * band_width, "u_high": (i + 1) * band_width}
        for p, i in white_index.items()
    ]

    black_keys = []
    for p in range(lowest_pitch, highest_pitch + 1):
        if is_white_key(p):
            continue
        lower_white, upper_white = p - 1, p + 1  # always white, for any black-key pitch class
        if lower_white not in white_index or upper_white not in white_index:
            continue  # black key at the very edge of the calibrated range -- no full white-key context
        boundary_u = white_index[upper_white] * band_width
        half_width = (band_width * black_key_width_ratio) / 2.0
        black_keys.append({"pitch": p, "u_low": boundary_u - half_width, "u_high": boundary_u + half_width})

    white_keys.sort(key=lambda k: k["u_low"])
    black_keys.sort(key=lambda k: k["u_low"])
    return white_keys, black_keys


def calibrate(
    top_left,
    top_right,
    bottom_left,
    bottom_right,
    lowest_pitch: int,
    highest_pitch: int,
    camera_id: str = "default",
    config: Optional[CameraEvidenceConfig] = None,
) -> dict:
    """Build a calibration dict from the keyboard's pixel corners and the
    MIDI pitch range it covers. Corners are (x, y) pixel pairs.
    """
    config = config or CameraEvidenceConfig()
    src = [tuple(top_left), tuple(top_right), tuple(bottom_left), tuple(bottom_right)]
    dst = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
    H = _solve_homography(src, dst)

    avg_width_px = (_dist(top_left, top_right) + _dist(bottom_left, bottom_right)) / 2.0
    avg_height_px = (_dist(top_left, bottom_left) + _dist(top_right, bottom_right)) / 2.0
    edge_tolerance_u = config.calibration_edge_tolerance_px / avg_width_px if avg_width_px else 0.0
    edge_tolerance_v = config.calibration_edge_tolerance_px / avg_height_px if avg_height_px else 0.0

    white_keys, black_keys = _build_key_layout(lowest_pitch, highest_pitch, config.black_key_width_ratio)

    return {
        "camera_id": camera_id,
        "corners": {
            "top_left": list(top_left),
            "top_right": list(top_right),
            "bottom_left": list(bottom_left),
            "bottom_right": list(bottom_right),
        },
        "lowest_pitch": lowest_pitch,
        "highest_pitch": highest_pitch,
        "black_key_width_ratio": config.black_key_width_ratio,
        "black_key_depth_ratio": config.black_key_depth_ratio,
        "edge_tolerance_u": edge_tolerance_u,
        "edge_tolerance_v": edge_tolerance_v,
        "homography": H.tolist(),
        "white_keys": white_keys,
        "black_keys": black_keys,
    }


def save_calibration(calibration: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(calibration, fh, indent=2)


def load_calibration(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def pixel_to_pitch(x: float, y: float, calibration: dict) -> Optional[int]:
    """Maps a camera pixel position to a MIDI pitch, or None if it falls
    outside the calibrated keyboard region.
    """
    H = np.asarray(calibration["homography"], dtype=float)
    mapped = _apply_homography(H, x, y)
    if mapped is None:
        return None
    u, v = mapped

    tol_u = calibration.get("edge_tolerance_u", 0.0)
    tol_v = calibration.get("edge_tolerance_v", 0.0)
    if not (-tol_u <= u <= 1.0 + tol_u and -tol_v <= v <= 1.0 + tol_v):
        return None
    u = min(1.0, max(0.0, u))
    v = min(1.0, max(0.0, v))

    if v <= calibration["black_key_depth_ratio"]:
        for key in calibration["black_keys"]:
            if key["u_low"] <= u <= key["u_high"]:
                return key["pitch"]
    for key in calibration["white_keys"]:
        if key["u_low"] <= u <= key["u_high"]:
            return key["pitch"]
    return None


def pitch_to_pixel(pitch: int, calibration: dict) -> Optional[tuple]:
    """Inverse of pixel_to_pitch: a representative pixel position (the
    center) for a given pitch's key, or None if that pitch isn't in the
    calibrated range. Used by SyntheticFingertipSource to fake a plausible
    fingertip trajectory from a reference.json.
    """
    key, is_black = None, False
    for candidate in calibration["white_keys"]:
        if candidate["pitch"] == pitch:
            key = candidate
            break
    if key is None:
        for candidate in calibration["black_keys"]:
            if candidate["pitch"] == pitch:
                key, is_black = candidate, True
                break
    if key is None:
        return None

    u = (key["u_low"] + key["u_high"]) / 2.0
    depth_ratio = calibration["black_key_depth_ratio"]
    v = depth_ratio / 2.0 if is_black else (depth_ratio + 1.0) / 2.0

    H = np.asarray(calibration["homography"], dtype=float)
    H_inv = np.linalg.inv(H)
    return _apply_homography(H_inv, u, v)
