"""Tunable thresholds and weights for the scoring engine, in one place."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ScoringConfig:
    # --- chord/event grouping ---
    chord_window_sec: float = 0.03  # notes within this onset window are one "event" (chord)

    # --- alignment (DTW) cost, final pass ---
    w_time: float = 1.0       # cost per second of |time residual|
    w_pitch: float = 2.0      # flat cost for a pitch mismatch on an otherwise-aligned pair
    gap_penalty: float = 1.5  # cost of skipping a note (becomes "missed" or "extra")

    # --- alignment (DTW), rough pass used only to find tempo-fit anchor pairs ---
    pass1_time_weight: float = 0.3  # weight on *fractional* time position in the rough pass

    # --- robust tempo fit (Theil-Sen) ---
    robust_fit_max_pairs: int = 2000  # cap on pairwise slopes sampled, for speed

    # --- piecewise/windowed tempo curve (absorbs real local tempo changes,
    # e.g. rubato, a sustained mid-piece speed-up, instead of letting the
    # residual against one global straight line accumulate) ---
    tempo_window_notes: int = 40   # confident-matched notes per local tempo-fit window
    tempo_window_step: int = 20    # step between successive windows (overlap = window - step)

    # --- classification tolerance ---
    tol_ms: float = 50.0
    tol_beat: Optional[float] = None  # e.g. 1/16; overrides tol_ms (via effective bpm) when set

    # --- scoring weights (intended to sum to 1.0) ---
    score_weight_pitch: float = 0.4
    score_weight_rhythm: float = 0.4
    score_weight_timing_stability: float = 0.2

    # --- tempo trend classification ---
    tempo_trend_min_slope_ms: float = 0.3  # ms/note; smaller than this is called "steady"

    def effective_tol_ms(self, bpm: float) -> float:
        """Resolve the timing tolerance to use in ms, given the tempo in force."""
        if self.tol_beat is not None:
            return self.tol_beat * (60000.0 / bpm)
        return self.tol_ms
