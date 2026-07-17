"""Shared onset detection with a refractory period, used by both
calibrate.py and rhythm_test.py.

A single physical tap/clap is not always one clean transient -- the impact
plus a secondary resonance/bounce can register as two separate onsets to a
generic detector, especially for hand-taps on a desk (unlike the synthetic
click track's single sharp burst). Left unfiltered, this double-counts taps
and corrupts any downstream interval/tempo estimate. `wait` enforces a
minimum gap between onsets at detection time; the post-hoc merge is a
belt-and-suspenders backstop in case something still slips through.
"""
from __future__ import annotations

import librosa
import numpy as np

HOP_LENGTH = 512
MIN_ONSET_GAP_SEC = 0.15


def detect_onsets(recording: np.ndarray, sr: int, min_gap_sec: float = MIN_ONSET_GAP_SEC) -> np.ndarray:
    wait_frames = max(1, int(min_gap_sec * sr / HOP_LENGTH))
    onsets = librosa.onset.onset_detect(
        y=recording, sr=sr, units="time", backtrack=False,
        hop_length=HOP_LENGTH, wait=wait_frames,
    )
    return merge_close_onsets(onsets, min_gap_sec)


def merge_close_onsets(onsets: np.ndarray, min_gap_sec: float) -> np.ndarray:
    if len(onsets) == 0:
        return onsets
    merged = [onsets[0]]
    for t in onsets[1:]:
        if t - merged[-1] >= min_gap_sec:
            merged.append(t)
    return np.array(merged)
