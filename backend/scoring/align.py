"""Alignment: group notes into chord events, then DTW/edit-distance match
reference notes against performance notes, absorbing the performance's tempo
(including genuine local tempo changes -- rubato, a mid-piece speed-up) before
classifying local timing errors.

Design in three stages (see score.score_performance for the orchestration):

1. `prepare_sequence` groups each side's own (already time-sorted) notes into
   chord events by onset proximity, then canonicalizes each event's member
   order by ascending pitch. Doing this independently on both sides lets a
   plain 1-D DTW match chord members correctly even if the performer's hand
   struck them in a different order, or the input lists ordered them
   differently -- without needing full bipartite (Hungarian) matching.
2. `fit_tempo_curve` runs a *rough*, pitch-primary alignment (pass 1) whose
   only job is to find confidently-matched pairs (exact pitch, low
   *normalized* time residual), then fits a robust (Theil-Sen) LOCAL
   slope+intercept within a sliding window of those pairs, one per window,
   and stitches the windows' center predictions into a piecewise-linear
   `TempoCurve`. A single global straight-line fit cannot track a real
   performance that speeds up or slows down partway through (the residual
   just accumulates and eventually confuses which notes correspond to which);
   a windowed fit absorbs that local drift while a single global fallback
   (see below) still covers small inputs where windowing isn't meaningful.
3. `align_notes` runs the real, final DTW (pass 2) with the curve's predicted
   time baked into the time-residual cost, producing the definitive
   match / substitution / deletion / insertion structure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .config import ScoringConfig


def group_into_events(onsets: list, window_sec: float) -> list:
    """Cluster time-sorted note *positions* [0..n) into chord events:
    consecutive notes within `window_sec` of the event's first note join it.
    """
    events: list = []
    current: list = []
    current_start = None
    for i, onset in enumerate(onsets):
        if current and onset - current_start > window_sec:
            events.append(current)
            current = []
            current_start = None
        if not current:
            current_start = onset
        current.append(i)
    if current:
        events.append(current)
    return events


def sort_events_by_pitch(pitches: list, events: list) -> list:
    """Permutation of positions where each chord event's members are
    reordered ascending by pitch -- canonicalizes voicing order.
    """
    order: list = []
    for event in events:
        order.extend(sorted(event, key=lambda i: pitches[i]))
    return order


def prepare_sequence(onsets_raw: list, pitches_raw: list, window_sec: float):
    """Time-sort, group into chord events, and canonicalize chord member
    order by pitch. Returns (onsets, pitches, orig_indices) where
    orig_indices[k] is the index into the *original* input lists for the
    note now at canonical position k.
    """
    order = sorted(range(len(onsets_raw)), key=lambda i: (onsets_raw[i], pitches_raw[i]))
    onsets_sorted = [onsets_raw[i] for i in order]
    pitches_sorted = [pitches_raw[i] for i in order]

    events = group_into_events(onsets_sorted, window_sec)
    perm = sort_events_by_pitch(pitches_sorted, events)

    final_order = [order[p] for p in perm]
    onsets_final = [onsets_raw[i] for i in final_order]
    pitches_final = [pitches_raw[i] for i in final_order]
    return onsets_final, pitches_final, final_order


def _dtw_align(
    n: int, m: int, pair_cost_fn: Callable[[int, int], float], gap_penalty: float
) -> list:
    """Classic O(N*M) global alignment (Needleman-Wunsch-style DTW) with a
    match/substitute step and independent skip steps on each side. Returns a
    list of (ref_position, perf_position) pairs, in order; either side may be
    None (a skip -- reference-only = deletion, performance-only = insertion).
    """
    dp = np.zeros((n + 1, m + 1))
    dp[:, 0] = np.arange(n + 1) * gap_penalty
    dp[0, :] = np.arange(m + 1) * gap_penalty
    # 0 = diagonal (match/substitute), 1 = up (ref skipped), 2 = left (perf skipped)
    backtrace = np.zeros((n + 1, m + 1), dtype=np.int8)
    backtrace[:, 0] = 1
    backtrace[0, :] = 2

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost_match = dp[i - 1, j - 1] + pair_cost_fn(i - 1, j - 1)
            cost_del = dp[i - 1, j] + gap_penalty
            cost_ins = dp[i, j - 1] + gap_penalty
            best, direction = cost_match, 0
            if cost_del < best:
                best, direction = cost_del, 1
            if cost_ins < best:
                best, direction = cost_ins, 2
            dp[i, j] = best
            backtrace[i, j] = direction

    pairs: list = []
    i, j = n, m
    while i > 0 or j > 0:
        d = backtrace[i, j]
        if i > 0 and j > 0 and d == 0:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and (j == 0 or d == 1):
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs


def _theil_sen_fit(xs: np.ndarray, ys: np.ndarray, max_pairs: int) -> tuple:
    """Robust slope+intercept via Theil-Sen (median of pairwise slopes) --
    resists outliers unlike least squares, and stays deterministic even when
    subsampled (an evenly-spaced subsample, never a random one).
    """
    n = len(xs)
    if n == 0:
        return 1.0, 0.0
    if n == 1:
        return 1.0, float(ys[0] - xs[0])

    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]

    i_idx, j_idx = np.triu_indices(n, k=1)
    total_pairs = len(i_idx)
    if total_pairs > max_pairs:
        pick = np.linspace(0, total_pairs - 1, max_pairs).astype(int)
        i_idx, j_idx = i_idx[pick], j_idx[pick]

    dx = xs[j_idx] - xs[i_idx]
    valid = np.abs(dx) > 1e-9
    if not np.any(valid):
        return 1.0, float(np.median(ys - xs))
    slopes = (ys[j_idx[valid]] - ys[i_idx[valid]]) / dx[valid]
    slope = float(np.median(slopes))
    intercept = float(np.median(ys - slope * xs))
    return slope, intercept


@dataclass
class TempoCurve:
    """Piecewise-linear map from reference time to predicted performance
    time, built from a handful of (ref_time, predicted_perf_time) anchor
    points -- linear interpolation between anchors, linear extrapolation
    (using the nearest segment's slope) outside their range.

    `representative_slope` is a single robust-fit slope over *all* the
    confident pairs (regardless of windowing) -- used for reporting
    (`global_tempo_ratio`) and as the extrapolation slope when there's only
    one anchor.
    """
    anchor_ref_times: np.ndarray
    anchor_perf_times: np.ndarray
    representative_slope: float

    def predict(self, ref_time: float) -> float:
        xs, ys = self.anchor_ref_times, self.anchor_perf_times
        if len(xs) == 1:
            return float(ys[0] + self.representative_slope * (ref_time - xs[0]))
        if ref_time <= xs[0]:
            local_slope = (ys[1] - ys[0]) / (xs[1] - xs[0]) if xs[1] != xs[0] else self.representative_slope
            return float(ys[0] + local_slope * (ref_time - xs[0]))
        if ref_time >= xs[-1]:
            local_slope = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]) if xs[-1] != xs[-2] else self.representative_slope
            return float(ys[-1] + local_slope * (ref_time - xs[-1]))
        return float(np.interp(ref_time, xs, ys))


def _find_confident_pairs(
    ref_onset: list, ref_pitch: list, perf_onset: list, perf_pitch: list, config: ScoringConfig
) -> tuple:
    """Pass 1: rough pitch-primary alignment (cost dominated by pitch match,
    with a small *normalized*-time tie-breaker so a uniform tempo difference
    doesn't distort matching) to find pairs confident enough (exact pitch
    match) to anchor a tempo fit. Returns sorted (confident_ref, confident_perf)
    arrays, by ref time.
    """
    ref_total = max(ref_onset) or 1.0
    perf_total = max(perf_onset) or 1.0

    def pair_cost(i: int, j: int) -> float:
        pitch_cost = 0.0 if ref_pitch[i] == perf_pitch[j] else config.w_pitch
        time_cost = config.pass1_time_weight * abs(
            ref_onset[i] / ref_total - perf_onset[j] / perf_total
        )
        return pitch_cost + time_cost

    pairs = _dtw_align(len(ref_onset), len(perf_onset), pair_cost, config.gap_penalty)

    confident = [
        (ref_onset[ref_i], perf_onset[perf_j])
        for ref_i, perf_j in pairs
        if ref_i is not None and perf_j is not None and ref_pitch[ref_i] == perf_pitch[perf_j]
    ]
    confident.sort(key=lambda pair: pair[0])
    confident_ref = np.array([pair[0] for pair in confident])
    confident_perf = np.array([pair[1] for pair in confident])
    return confident_ref, confident_perf


def fit_tempo_curve(
    ref_onset: list, ref_pitch: list, perf_onset: list, perf_pitch: list, config: ScoringConfig
) -> TempoCurve:
    """Pass 1: find confidently-matched pairs, then fit a piecewise-linear
    tempo curve -- a robust (Theil-Sen) LOCAL slope+intercept per sliding
    window of pairs, stitched together -- so a genuine local tempo change
    (rubato, a sustained speed-up partway through) gets absorbed instead of
    accumulating as residual against one global straight line.
    """
    if not ref_onset or not perf_onset:
        return TempoCurve(np.array([0.0]), np.array([0.0]), 1.0)

    confident_ref, confident_perf = _find_confident_pairs(
        ref_onset, ref_pitch, perf_onset, perf_pitch, config
    )

    representative_slope, representative_intercept = _theil_sen_fit(
        confident_ref, confident_perf, config.robust_fit_max_pairs
    )

    n = len(confident_ref)
    if n < 2:
        return TempoCurve(np.array([0.0]), np.array([representative_intercept]), representative_slope)

    window = config.tempo_window_notes
    step = config.tempo_window_step

    if n < window:
        # too few confident pairs to window meaningfully -- one global segment
        anchor_ref = np.array([confident_ref[0], confident_ref[-1]])
        anchor_perf = representative_slope * anchor_ref + representative_intercept
        return TempoCurve(anchor_ref, anchor_perf, representative_slope)

    anchor_ref_times, anchor_perf_times = [], []
    first_fit = last_fit = None
    start = 0
    while True:
        end = min(n, start + window)
        window_ref = confident_ref[start:end]
        window_perf = confident_perf[start:end]
        local_slope, local_intercept = _theil_sen_fit(
            window_ref, window_perf, config.robust_fit_max_pairs
        )
        if first_fit is None:
            first_fit = (local_slope, local_intercept)
        last_fit = (local_slope, local_intercept)
        center_ref = float(np.median(window_ref))
        anchor_ref_times.append(center_ref)
        anchor_perf_times.append(local_slope * center_ref + local_intercept)
        if end == n:
            break
        start += step

    # A window's own anchor sits at its MEDIAN ref-time, which for unevenly-
    # spaced/sparse confident pairs (typical on a real recording, unlike the
    # evenly-spaced synthetic data in test_tempo_curve.py) can land well
    # inside the piece even for the very first window -- e.g. observed on a
    # real recording: first anchor at ref=8.1s despite confident pairs
    # starting at ref=0.0s. Predicting anything before that first anchor then
    # EXTRAPOLATES using the slope between the first two anchors (a DIFFERENT
    # window's fit) rather than using the first window's own fit at the point
    # that actually needs it, which can systematically misjudge the opening
    # notes as a large, spurious "rush" (or drag) even when the piece is
    # locally steady there. Extending the first/last window's own local fit
    # out to the true first/last confident-pair time closes that gap, so any
    # ref-time within the confident pairs' actual span is interpolated
    # between anchors instead of extrapolated from an unrelated window.
    first_ref = confident_ref[0]
    if first_ref < anchor_ref_times[0]:
        slope, intercept = first_fit
        anchor_ref_times.insert(0, float(first_ref))
        anchor_perf_times.insert(0, slope * first_ref + intercept)
    last_ref = confident_ref[-1]
    if last_ref > anchor_ref_times[-1]:
        slope, intercept = last_fit
        anchor_ref_times.append(float(last_ref))
        anchor_perf_times.append(slope * last_ref + intercept)

    return TempoCurve(
        np.array(anchor_ref_times), np.array(anchor_perf_times), representative_slope
    )


def align_notes(
    ref_onset: list, ref_pitch: list, perf_onset: list, perf_pitch: list,
    config: ScoringConfig, tempo_curve: TempoCurve,
) -> list:
    """Pass 2 (final): DTW with the real cost function, mapping reference
    time onto the performance's timeline via the fitted tempo curve.
    """
    def pair_cost(i: int, j: int) -> float:
        predicted = tempo_curve.predict(ref_onset[i])
        time_residual = abs(perf_onset[j] - predicted)
        pitch_cost = 0.0 if ref_pitch[i] == perf_pitch[j] else config.w_pitch
        return config.w_time * time_residual + pitch_cost

    return _dtw_align(len(ref_onset), len(perf_onset), pair_cost, config.gap_penalty)
