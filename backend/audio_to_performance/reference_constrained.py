"""Reference-constrained audio grading helpers.

For a known practice score on a known electronic keyboard, open-ended
transcription can be the wrong problem. This module verifies the expected
reference notes directly in the audio, then emits a performance-note list that
the existing symbolic scorer can grade.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import librosa
import numpy as np

from backend.hardware import KEYBOARD_RANGE
from backend.scoring.align import _dtw_align, group_into_events

from .constrained_verification import (
    CQTFrame,
    ConstrainedVerificationConfig,
    get_candidates,
    load_keyboard_profile,
    score_candidate,
)


@dataclass
class ReferenceConstrainedConfig:
    keyboard_range: Optional[tuple[int, int]] = KEYBOARD_RANGE
    allowed_pitches: Optional[tuple[int, ...]] = None
    keyboard_profile: Optional[dict] = None
    keyboard_profile_weight: float = 0.75
    onset_window_sec: float = 0.16
    min_winner_confidence: float = 0.18
    min_ref_score_ratio: float = 0.65
    min_energy_above_floor_ratio: float = 4.0
    emit_wrong_pitch: bool = False
    frame_length: int = 4096
    hop_length: int = 512
    cqt_fmin_hz: float = 27.5
    cqt_bins_per_octave: int = 36
    cqt_n_octaves: int = 8
    onset_delta: float = 0.22
    onset_wait_frames: int = 3
    onset_min_confidence: float = 0.12
    onset_min_gap_sec: float = 0.08
    onset_pitch_window_before_sec: float = 0.02
    onset_pitch_window_after_sec: float = 0.12
    chord_score_ratio: float = 0.55
    max_pitches_per_onset: int = 1
    reference_event_window_sec: float = 0.18
    reference_pitch_score_ratio: float = 0.38
    reference_guided_fallback_top_pitch: bool = False
    audio_compare_tol_ms: float = 250.0
    audio_compare_gap_cost: float = 0.08
    duplicate_extra_window_sec: float = 0.3

    # --- per-pitch adaptive ref_ratio threshold ---
    # This specific electronic keyboard's low-register keys have a
    # systematically WEAK fundamental (confirmed across multiple keybank
    # profile entries: pitch 48's fundamental is only ~6% of its harmonic
    # energy, with the 2nd/3rd harmonic dominating instead, improving
    # gradually up through the register -- by pitch 60 the fundamental is
    # the strongest component at ~37%). Traced two independently-found
    # false "missed"/"wrong_pitch_candidate" cases (twinkle_twinkle's F3,
    # silent_night_easy's G3) to the EXACT SAME root cause: `confidence` was
    # never the bottleneck (0.54-0.57, comfortably above
    # min_winner_confidence=0.18) -- `ref_ratio` was, landing at 0.63-0.64,
    # just under the flat min_ref_score_ratio=0.65 floor. A uniform
    # threshold penalizes these pitches for a hardware trait, not a
    # transcription failure, so the ratio floor is discounted per-pitch
    # using the profile's own measured fundamental share -- pitches with a
    # strong fundamental (>= weak_fundamental_reference_share) are
    # unaffected (discount 1.0, i.e. the original flat threshold).
    weak_fundamental_ratio_floor: float = 0.85
    weak_fundamental_reference_share: float = 0.3

    # --- reference<->onset DTW alignment (transcribe_reference_dtw) ---
    # Unlike reference-grid's single linear time_scale (breaks under real
    # tempo rubato) or reference-guided-onsets' reference-time window (same
    # problem, just windowed), this mode detects real onsets and lets a DTW
    # match reference note-events to them using dense pitch evidence as the
    # primary cost, with only a WEAK global-position tie-breaker for time --
    # so it tolerates rubato and still disambiguates repeated pitches via
    # sequence order, the same way backend/scoring/align.py's own pass-1 does.
    dtw_pitch_cost_weight: float = 1.5   # cost per pitch at zero evidence; > dtw_gap_penalty so a bad match is skipped instead of forced
    dtw_time_weight: float = 0.3         # weight on |normalized ref position - normalized onset position|, tie-breaker only
    dtw_gap_penalty: float = 1.2         # cost of leaving a reference event or a detected onset unmatched
    dtw_chord_window_sec: float = 0.05   # groups reference notes into chord events for the DTW step


def _ref_score_ratio_threshold(pitch: int, config: ReferenceConstrainedConfig) -> float:
    """min_ref_score_ratio, discounted for this specific pitch if the loaded
    keyboard profile shows it has a weak fundamental (see
    ReferenceConstrainedConfig's docstring above for why). Linear ramp: no
    discount at/above weak_fundamental_reference_share, down to
    weak_fundamental_ratio_floor at a fundamental share of 0. Falls back to
    the flat config.min_ref_score_ratio when there's no profile, no entry
    for this pitch, or no harmonic data on it.
    """
    if not config.keyboard_profile:
        return config.min_ref_score_ratio
    note_profile = config.keyboard_profile.get("notes", {}).get(str(pitch))
    if not note_profile:
        return config.min_ref_score_ratio
    harmonics = note_profile.get("harmonic_energy_mean")
    if not harmonics:
        return config.min_ref_score_ratio
    fundamental_share = float(harmonics[0])
    floor = config.weak_fundamental_ratio_floor
    reference_share = config.weak_fundamental_reference_share
    if reference_share <= 0:
        return config.min_ref_score_ratio
    discount = floor + (1.0 - floor) * min(1.0, fundamental_share / reference_share)
    return config.min_ref_score_ratio * discount


def _pitch_allowed(pitch: int, config: ReferenceConstrainedConfig) -> bool:
    if config.keyboard_range is not None:
        low, high = config.keyboard_range
        if not (low <= pitch <= high):
            return False
    if config.allowed_pitches is not None and pitch not in set(config.allowed_pitches):
        return False
    return True


def _candidate_pitches(config: ReferenceConstrainedConfig) -> list[int]:
    if config.allowed_pitches is not None:
        return sorted(
            int(pitch)
            for pitch in config.allowed_pitches
            if config.keyboard_range is None
            or config.keyboard_range[0] <= int(pitch) <= config.keyboard_range[1]
        )
    low, high = config.keyboard_range if config.keyboard_range is not None else (0, 127)
    return list(range(low, high + 1))


def estimate_active_audio_range(audio: np.ndarray, sr: int, frame_length: int = 2048, hop_length: int = 512) -> tuple:
    """Return the first/last active audio times using an adaptive RMS floor."""
    if len(audio) == 0:
        return 0.0, 0.0
    rms = librosa.feature.rms(y=audio, frame_length=frame_length, hop_length=hop_length)[0]
    if len(rms) == 0 or float(rms.max()) <= 0:
        return 0.0, len(audio) / sr
    threshold = max(float(np.percentile(rms, 20)) * 1.5, float(rms.max()) * 0.02)
    active = np.where(rms >= threshold)[0]
    if len(active) == 0:
        return 0.0, len(audio) / sr
    times = librosa.frames_to_time(active, sr=sr, hop_length=hop_length)
    start = max(0.0, float(times[0]) - 0.05)
    end = min(len(audio) / sr, float(times[-1]) + 0.05)
    if end <= start:
        return 0.0, len(audio) / sr
    return start, end


def reference_duration(reference: dict) -> float:
    notes = reference.get("notes", [])
    if not notes:
        return 0.0
    return max(float(n["onset_sec"]) + float(n.get("dur_sec", 0.0) or 0.0) for n in notes)


def _compute_cqt_frame(audio_window: np.ndarray, sr: int, config: ReferenceConstrainedConfig) -> CQTFrame:
    n_bins = config.cqt_bins_per_octave * config.cqt_n_octaves
    if audio_window is None or len(audio_window) < 64:
        return CQTFrame(np.zeros(n_bins), config.cqt_fmin_hz, config.cqt_bins_per_octave)
    cqt = librosa.cqt(
        audio_window,
        sr=sr,
        fmin=config.cqt_fmin_hz,
        bins_per_octave=config.cqt_bins_per_octave,
        n_bins=n_bins,
    )
    return CQTFrame(np.abs(cqt).mean(axis=1), config.cqt_fmin_hz, config.cqt_bins_per_octave)


def _estimate_energy_floor(
    audio: np.ndarray, sr: int, config: ReferenceConstrainedConfig,
    active_start: float = 0.0, active_end: Optional[float] = None,
) -> float:
    """What does "nothing was played here, just room noise" look like in
    THIS specific recording (device/gain/room vary, so this can't be a
    fixed constant)?

    This exists because the per-note "confidence" (a candidate pitch's
    share of the total scored energy among ~9 candidates) has no way to
    reject "no signal at all" on its own -- pure noise still has a highest-
    scoring candidate purely from random fluctuation among a handful of
    options, and confirmed on a genuinely silent recording: every "winning"
    candidate's confidence landed at 0.22-0.38, comfortably above
    min_winner_confidence=0.18, even though nothing was played anywhere in
    it. An absolute floor on the raw energy is the only way to catch that.

    Prefer the audio strictly AFTER the reference's estimated last note
    (genuine trailing silence -- present both in a real recording's natural
    pause after finishing, and in synthesized test audio's --tail-sec
    padding) as the calibration source: a first attempt that instead
    sampled windows spread across the WHOLE recording and took a low (40th)
    percentile massively over-estimated the floor for a continuously-busy
    piece with no real gaps between notes -- most sampled windows landed on
    or beside an actual note, so even a low percentile was still measuring
    "quiet part of a real note", not silence, and rejected genuine
    detections as noise. Falls back to a low (10th) percentile of the whole
    recording only when there isn't enough trailing audio to sample.
    """
    n = len(audio)
    window = int(config.onset_window_sec * 2 * sr)
    if n == 0 or window <= 0:
        return 0.0

    tail_start_sample = int((active_end or 0.0) * sr)
    tail = audio[tail_start_sample:] if 0 < tail_start_sample < n else audio[0:0]
    if len(tail) >= window * 2:
        step = max(window // 2, 1)
        totals = [
            float(np.sum(_compute_cqt_frame(tail[start:start + window], sr, config).magnitudes))
            for start in range(0, len(tail) - window, step)
        ]
        if totals:
            return float(np.percentile(totals, 60))

    if window >= n:
        return 0.0
    step = max(window, n // 40)
    totals = [
        float(np.sum(_compute_cqt_frame(audio[start:start + window], sr, config).magnitudes))
        for start in range(0, n - window, step)
    ]
    return float(np.percentile(totals, 10)) if totals else 0.0


def _verification_config(config: ReferenceConstrainedConfig) -> ConstrainedVerificationConfig:
    return ConstrainedVerificationConfig(
        keyboard_range=config.keyboard_range,
        keyboard_profile=config.keyboard_profile,
        keyboard_profile_weight=config.keyboard_profile_weight,
        onset_window_sec=config.onset_window_sec,
        cqt_fmin_hz=config.cqt_fmin_hz,
        cqt_bins_per_octave=config.cqt_bins_per_octave,
        cqt_n_octaves=config.cqt_n_octaves,
    )


def _estimate_time_alignment(
    reference: dict,
    audio: np.ndarray,
    sr: int,
    config: ReferenceConstrainedConfig,
) -> tuple[float, float]:
    """Anchor audio-time <-> reference-time scaling to real detected onsets
    rather than the coarse "where is the audio active" RMS region.

    The RMS-region heuristic excludes the last note's quiet decay tail (it
    falls below the activity threshold before the note is really over), which
    for a piece with many notes compounds into several hundred ms of drift by
    the end -- easily overrunning onset_window_sec, so later reference notes
    get checked against the wrong window of audio entirely and are wrongly
    scored as missed/wrong_pitch. Onset detection lands on the actual attack
    times, which is a far more precise anchor than an overall energy envelope.
    """
    notes = reference.get("notes", [])
    onset_times = sorted(float(n["onset_sec"]) for n in notes)
    if len(onset_times) < 2:
        return estimate_active_audio_range(audio, sr)

    ref_first, ref_last = onset_times[0], onset_times[-1]
    if ref_last <= ref_first:
        return estimate_active_audio_range(audio, sr)

    detected = _detect_audio_onsets(audio, sr, config)
    if len(detected) < 2:
        return estimate_active_audio_range(audio, sr)

    audio_first, audio_last = detected[0], detected[-1]
    time_scale = (audio_last - audio_first) / (ref_last - ref_first)
    if time_scale <= 0:
        return estimate_active_audio_range(audio, sr)

    active_start = audio_first - ref_first * time_scale
    active_end = active_start + reference_duration(reference) * time_scale
    return active_start, active_end


def transcribe_reference_constrained(
    reference: dict,
    audio: np.ndarray,
    sr: int,
    config: Optional[ReferenceConstrainedConfig] = None,
) -> tuple[list, dict]:
    """Emit performance notes by verifying expected reference notes in audio.

    The output performance list uses AUDIO time. The existing scorer then fits
    its tempo curve exactly as it would for a MIDI keyboard performance.
    """
    config = config or ReferenceConstrainedConfig()
    active_start, active_end = _estimate_time_alignment(reference, audio, sr, config)
    ref_duration = reference_duration(reference)
    if ref_duration <= 0:
        return [], {"active_start_sec": active_start, "active_end_sec": active_end, "time_scale": None}

    time_scale = (active_end - active_start) / ref_duration
    verifier_config = _verification_config(config)
    energy_floor = _estimate_energy_floor(audio, sr, config, active_start=active_start, active_end=active_end)
    performance = []
    debug_notes = []

    for idx, ref_note in enumerate(reference.get("notes", [])):
        ref_pitch = int(ref_note["pitch"])
        if not _pitch_allowed(ref_pitch, config):
            debug_notes.append({"ref_index": idx, "pitch": ref_pitch, "decision": "unsupported_pitch"})
            continue

        expected_onset = active_start + float(ref_note["onset_sec"]) * time_scale
        start_sample = max(0, int((expected_onset - config.onset_window_sec) * sr))
        end_sample = min(len(audio), int((expected_onset + config.onset_window_sec) * sr))
        frame = _compute_cqt_frame(audio[start_sample:end_sample], sr, config)
        frame_energy = float(np.sum(frame.magnitudes))

        # The relative confidence/ratio checks below compare candidates only
        # against EACH OTHER -- pure noise still has a highest-scoring
        # candidate from random fluctuation among a handful of options, so
        # they can't by themselves tell "a note was played" from "nothing
        # was played here at all". Gate on absolute energy first.
        if frame_energy < energy_floor * config.min_energy_above_floor_ratio:
            debug_notes.append({
                "ref_index": idx, "pitch": ref_pitch,
                "expected_onset_sec": round(expected_onset, 4),
                "frame_energy": round(frame_energy, 6), "energy_floor": round(energy_floor, 6),
                "decision": "below_noise_floor",
            })
            continue

        candidates = [
            pitch
            for pitch in get_candidates(ref_pitch, config.keyboard_range, verifier_config)
            if _pitch_allowed(pitch, config)
        ]
        scores = {c: score_candidate(frame, c, ref_pitch, candidates, verifier_config) for c in candidates}
        total = float(sum(scores.values()))
        winner = max(scores, key=scores.get) if scores else None
        confidence = (scores[winner] / total) if winner is not None and total > 0 else 0.0
        ref_score = scores.get(ref_pitch, 0.0)
        winner_score = scores.get(winner, 0.0) if winner is not None else 0.0
        ref_ratio = (ref_score / winner_score) if winner_score > 0 else 0.0

        decision = "missed"
        emit_pitch = None
        if winner == ref_pitch and confidence >= config.min_winner_confidence:
            decision = "expected_pitch"
            emit_pitch = ref_pitch
        elif ref_score > 0 and ref_ratio >= _ref_score_ratio_threshold(ref_pitch, config) and confidence >= config.min_winner_confidence:
            decision = "expected_pitch_near_winner"
            emit_pitch = ref_pitch
        elif config.emit_wrong_pitch and winner is not None and confidence >= config.min_winner_confidence:
            decision = "wrong_pitch_candidate"
            emit_pitch = winner

        debug_notes.append({
            "ref_index": idx,
            "pitch": ref_pitch,
            "expected_onset_sec": round(expected_onset, 4),
            "winner": winner,
            "confidence": round(float(confidence), 4),
            "ref_ratio": round(float(ref_ratio), 4),
            "decision": decision,
        })
        if emit_pitch is None:
            continue
        dur = float(ref_note.get("dur_sec", 0.2) or 0.2) * time_scale
        performance.append({
            "pitch": int(emit_pitch),
            "onset_sec": round(float(expected_onset), 6),
            "dur_sec": round(max(0.05, dur), 6),
            "velocity": 80,
        })

    debug = {
        "active_start_sec": round(active_start, 6),
        "active_end_sec": round(active_end, 6),
        "reference_duration_sec": round(ref_duration, 6),
        "time_scale": round(time_scale, 6),
        "emitted_notes": len(performance),
        "reference_notes": len(reference.get("notes", [])),
        "notes": debug_notes,
    }
    return performance, debug


def _detect_audio_onsets(audio: np.ndarray, sr: int, config: ReferenceConstrainedConfig) -> list[float]:
    onset_env = librosa.onset.onset_strength(y=audio, sr=sr, hop_length=config.hop_length)
    frames = librosa.onset.onset_detect(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=config.hop_length,
        units="frames",
        backtrack=True,
        pre_max=3,
        post_max=3,
        pre_avg=8,
        post_avg=8,
        delta=config.onset_delta,
        wait=config.onset_wait_frames,
    )
    times = librosa.frames_to_time(frames, sr=sr, hop_length=config.hop_length)
    kept = []
    last = -float("inf")
    for t in times:
        t = float(t)
        if t - last < config.onset_min_gap_sec:
            continue
        kept.append(t)
        last = t
    return kept


def _pitch_scores_for_onset(
    audio: np.ndarray,
    sr: int,
    onset_sec: float,
    config: ReferenceConstrainedConfig,
) -> tuple[dict[int, float], float]:
    start = max(0, int((onset_sec - config.onset_pitch_window_before_sec) * sr))
    end = min(len(audio), int((onset_sec + config.onset_pitch_window_after_sec) * sr))
    frame = _compute_cqt_frame(audio[start:end], sr, config)
    candidates = _candidate_pitches(config)
    verifier_config = _verification_config(config)
    scores = {
        pitch: score_candidate(frame, pitch, pitch, candidates, verifier_config)
        for pitch in candidates
    }
    total = float(sum(scores.values()))
    return scores, total


def _select_onset_pitches(scores: dict[int, float], total: float, config: ReferenceConstrainedConfig) -> list[int]:
    if total <= 0:
        return []
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] / total < config.onset_min_confidence:
        return []

    selected = []
    top_score = ranked[0][1]
    for pitch, score in ranked:
        if score < top_score * config.chord_score_ratio:
            break
        # Avoid emitting obvious octave/harmonic duplicates from the same onset.
        if any(abs(pitch - existing) in {12, 19, 24} for existing in selected):
            continue
        selected.append(pitch)
        if len(selected) >= config.max_pitches_per_onset:
            break
    return sorted(selected)


def transcribe_onset_first(
    audio: np.ndarray,
    sr: int,
    config: Optional[ReferenceConstrainedConfig] = None,
) -> tuple[list, dict]:
    """Transcribe actual audio onsets without Basic Pitch.

    This is the honest no-Basic-Pitch path: detect attacks in the recording,
    estimate one or more pitches at each attack, and emit those real detected
    note events. It does not place notes on the reference grid.
    """
    config = config or ReferenceConstrainedConfig()
    onset_times = _detect_audio_onsets(audio, sr, config)
    performance = []
    debug_events = []
    for onset_sec in onset_times:
        scores, total = _pitch_scores_for_onset(audio, sr, onset_sec, config)
        pitches = _select_onset_pitches(scores, total, config)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:6]
        debug_events.append({
            "onset_sec": round(onset_sec, 6),
            "selected_pitches": pitches,
            "top_candidates": [
                {"pitch": pitch, "score": round(float(score), 6)}
                for pitch, score in ranked
            ],
            "confidence": round(float(ranked[0][1] / total), 4) if ranked and total > 0 else 0.0,
        })
        for pitch in pitches:
            performance.append({
                "pitch": int(pitch),
                "onset_sec": round(float(onset_sec), 6),
                "dur_sec": 0.18,
                "velocity": 80,
            })
    debug = {
        "mode": "onset_first",
        "detected_onsets": len(onset_times),
        "emitted_notes": len(performance),
        "events": debug_events,
    }
    return performance, debug


def _reference_pitches_near_audio_onset(
    reference: dict,
    onset_sec: float,
    active_start: float,
    time_scale: float,
    config: ReferenceConstrainedConfig,
) -> list[int]:
    if time_scale <= 0:
        return []
    ref_time = (onset_sec - active_start) / time_scale
    window = config.reference_event_window_sec / time_scale
    pitches = {
        int(note["pitch"])
        for note in reference.get("notes", [])
        if abs(float(note["onset_sec"]) - ref_time) <= window
    }
    pitches = {p for p in pitches if _pitch_allowed(p, config)}
    return sorted(pitches)


def transcribe_reference_guided_onsets(
    reference: dict,
    audio: np.ndarray,
    sr: int,
    config: Optional[ReferenceConstrainedConfig] = None,
) -> tuple[list, dict]:
    """Detect real audio onsets, then use the reference only to constrain pitch.

    Unlike `transcribe_reference_constrained`, this does not place notes on
    the reference time grid. It uses actual detected onset times, but avoids
    picking a stronger bass/harmonic when the expected reference pitch has
    enough local evidence.
    """
    config = config or ReferenceConstrainedConfig()
    active_start, active_end = estimate_active_audio_range(audio, sr)
    ref_duration = reference_duration(reference)
    time_scale = (active_end - active_start) / ref_duration if ref_duration > 0 else 1.0
    onset_times = _detect_audio_onsets(audio, sr, config)
    performance = []
    debug_events = []

    for onset_sec in onset_times:
        scores, total = _pitch_scores_for_onset(audio, sr, onset_sec, config)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if not ranked or total <= 0:
            continue
        top_score = ranked[0][1]
        top_confidence = top_score / total
        if top_confidence < config.onset_min_confidence:
            selected = []
            decision = "below_confidence"
        else:
            reference_pitches = _reference_pitches_near_audio_onset(
                reference, onset_sec, active_start, time_scale, config
            )
            selected = [
                pitch for pitch in reference_pitches
                if scores.get(pitch, 0.0) >= top_score * config.reference_pitch_score_ratio
            ][:config.max_pitches_per_onset]
            if selected:
                decision = "reference_pitch"
            elif config.reference_guided_fallback_top_pitch:
                selected = _select_onset_pitches(scores, total, config)
                decision = "fallback_top_pitch" if selected else "no_pitch"
            else:
                selected = []
                decision = "no_reference_pitch_evidence"

        debug_events.append({
            "onset_sec": round(float(onset_sec), 6),
            "reference_pitches": _reference_pitches_near_audio_onset(
                reference, onset_sec, active_start, time_scale, config
            ),
            "selected_pitches": selected,
            "decision": decision,
            "top_candidates": [
                {"pitch": pitch, "score": round(float(score), 6)}
                for pitch, score in ranked[:6]
            ],
            "confidence": round(float(top_confidence), 4),
        })
        for pitch in selected:
            performance.append({
                "pitch": int(pitch),
                "onset_sec": round(float(onset_sec), 6),
                "dur_sec": 0.18,
                "velocity": 80,
            })

    debug = {
        "mode": "reference_guided_onsets",
        "active_start_sec": round(active_start, 6),
        "active_end_sec": round(active_end, 6),
        "reference_duration_sec": round(ref_duration, 6),
        "time_scale": round(time_scale, 6),
        "detected_onsets": len(onset_times),
        "emitted_notes": len(performance),
        "events": debug_events,
    }
    return performance, debug


def _reference_note_events(reference: dict, window_sec: float) -> tuple[list[dict], list[dict]]:
    """Group reference notes (sorted by onset) into chord events for the DTW
    step -- mirrors backend.scoring.align's own chord grouping, just applied
    to the reference side only (the "onset" side is real detected audio
    onsets, not a second note list, so there is nothing to canonicalize there).
    """
    notes = sorted(reference.get("notes", []), key=lambda n: (float(n["onset_sec"]), int(n["pitch"])))
    onsets = [float(n["onset_sec"]) for n in notes]
    groups = group_into_events(onsets, window_sec)
    events = [
        {"onset_sec": onsets[idxs[0]], "pitches": sorted(int(notes[i]["pitch"]) for i in idxs)}
        for idxs in groups
    ]
    return events, notes


def transcribe_reference_dtw(
    reference: dict,
    audio: np.ndarray,
    sr: int,
    config: Optional[ReferenceConstrainedConfig] = None,
) -> tuple[list, dict]:
    """Detect real audio onsets, then DTW-match reference note-events to them
    directly on dense pitch evidence -- not a linear time grid, and not a
    reference-time window.

    Both reference-grid (one global linear time_scale) and reference-guided-
    onsets (a reference-time window derived from that same kind of estimate)
    make a single global assumption about how reference-time maps to audio-
    time, which a real performance's tempo rubato breaks -- confirmed on real
    recordings where neither improves discrimination between correct and
    deliberately-wrong playing over any threshold setting (see repo history /
    validation notes for the sweep). This instead treats "which reference
    note-event corresponds to which detected onset" itself as the alignment
    problem: the DTW cost is dominated by how well each onset's audio
    evidence supports the reference event's expected pitch(es) (the same
    candidate/harmonic-aware CQT scoring already used for grid verification),
    with only a WEAK tie-breaker on normalized (0..1) position-in-piece to
    disambiguate otherwise-identical repeats of the same pitch -- never a hard
    time window. This mirrors how backend/scoring/align.py's own pass-1 anchors
    a tempo curve from pitch-primary matches, just applied one step earlier,
    before any pitch label is committed.

    The emitted performance list uses the REAL detected onset times (not
    projected grid positions), so downstream backend.scoring.score_performance
    -- which re-derives its own tempo curve from this now near-1:1
    correspondence -- has an easy time producing accurate timing_off/correct
    classifications.
    """
    config = config or ReferenceConstrainedConfig()
    onset_times = _detect_audio_onsets(audio, sr, config)
    ref_events, _ref_notes_sorted = _reference_note_events(reference, config.dtw_chord_window_sec)

    if not onset_times or not ref_events:
        return [], {
            "mode": "reference_dtw",
            "detected_onsets": len(onset_times),
            "reference_events": len(ref_events),
            "emitted_notes": 0,
            "notes": [],
        }

    active_start, active_end = estimate_active_audio_range(audio, sr)
    energy_floor = _estimate_energy_floor(audio, sr, config, active_start=active_start, active_end=active_end)
    verifier_config = _verification_config(config)

    onset_frames = []
    for onset_sec in onset_times:
        start = max(0, int((onset_sec - config.onset_pitch_window_before_sec) * sr))
        end = min(len(audio), int((onset_sec + config.onset_pitch_window_after_sec) * sr))
        frame = _compute_cqt_frame(audio[start:end], sr, config)
        energy = float(np.sum(frame.magnitudes))
        onset_frames.append({"onset_sec": onset_sec, "frame": frame, "energy": energy})

    def _below_floor(energy: float) -> bool:
        return energy < energy_floor * config.min_energy_above_floor_ratio

    ref_first = ref_events[0]["onset_sec"]
    ref_span = (ref_events[-1]["onset_sec"] - ref_first) or 1.0
    onset_first = onset_times[0]
    onset_span = (onset_times[-1] - onset_first) or 1.0

    # (onset_index, pitch) -> (evidence_ratio_for_cost, confidence, exact_ratio)
    eval_cache: dict[tuple[int, int], tuple[float, float, float]] = {}

    def _evaluate(onset_idx: int, pitch: int) -> tuple[float, float, float]:
        key = (onset_idx, pitch)
        cached = eval_cache.get(key)
        if cached is not None:
            return cached
        onset_info = onset_frames[onset_idx]
        if _below_floor(onset_info["energy"]):
            result = (0.0, 0.0, 0.0)
            eval_cache[key] = result
            return result
        candidates = [
            c for c in get_candidates(pitch, config.keyboard_range, verifier_config)
            if _pitch_allowed(c, config)
        ]
        scores = {c: score_candidate(onset_info["frame"], c, pitch, candidates, verifier_config) for c in candidates}
        total = float(sum(scores.values()))
        if total <= 0:
            result = (0.0, 0.0, 0.0)
            eval_cache[key] = result
            return result
        winner = max(scores, key=scores.get)
        winner_score = scores[winner]
        confidence = winner_score / total
        pitch_score = scores.get(pitch, 0.0)
        exact_ratio = 1.0 if winner == pitch else (pitch_score / winner_score if winner_score > 0 else 0.0)
        cost_ratio = exact_ratio if confidence >= config.min_winner_confidence else exact_ratio * 0.4
        result = (cost_ratio, confidence, exact_ratio)
        eval_cache[key] = result
        return result

    def pair_cost(i: int, j: int) -> float:
        event = ref_events[i]
        pitch_cost = sum(
            config.dtw_pitch_cost_weight * (1.0 - _evaluate(j, pitch)[0])
            for pitch in event["pitches"]
        )
        norm_ref = (event["onset_sec"] - ref_first) / ref_span
        norm_onset = (onset_frames[j]["onset_sec"] - onset_first) / onset_span
        time_cost = config.dtw_time_weight * abs(norm_ref - norm_onset)
        return pitch_cost + time_cost

    pairs = _dtw_align(len(ref_events), len(onset_times), pair_cost, config.dtw_gap_penalty)

    # Full-keyboard-candidate winner for one onset, independent of any single
    # expected reference pitch -- used to name what was ACTUALLY likely played
    # when a matched onset fails the expected-pitch check, so that case can be
    # emitted as a genuine wrong_pitch (config.emit_wrong_pitch) rather than
    # only ever "missed" (which would blind this mode to real wrong notes the
    # same way it would if wrong_pitch were never checked at all).
    onset_winner_cache: dict[int, tuple] = {}

    def _onset_full_winner(onset_idx: int) -> tuple:
        cached = onset_winner_cache.get(onset_idx)
        if cached is not None:
            return cached
        onset_info = onset_frames[onset_idx]
        if _below_floor(onset_info["energy"]):
            result = (None, 0.0)
        else:
            candidates = _candidate_pitches(config)
            scores = {c: score_candidate(onset_info["frame"], c, c, candidates, verifier_config) for c in candidates}
            total = float(sum(scores.values()))
            if total <= 0:
                result = (None, 0.0)
            else:
                winner = max(scores, key=scores.get)
                result = (winner, scores[winner] / total)
        onset_winner_cache[onset_idx] = result
        return result

    performance = []
    debug_notes = []
    matched_onset_indices: set[int] = set()

    for pos_ref, pos_onset in pairs:
        if pos_ref is None:
            continue
        event = ref_events[pos_ref]
        if pos_onset is None:
            for pitch in event["pitches"]:
                debug_notes.append({
                    "pitch": pitch, "ref_onset_sec": round(event["onset_sec"], 4),
                    "decision": "missed_no_onset_match",
                })
            continue
        matched_onset_indices.add(pos_onset)
        onset_sec = onset_frames[pos_onset]["onset_sec"]

        pitch_decisions = []
        for pitch in event["pitches"]:
            _cost_ratio, confidence, exact_ratio = _evaluate(pos_onset, pitch)
            confident_enough = confidence >= config.min_winner_confidence
            decision = "expected_pitch" if confident_enough and exact_ratio >= _ref_score_ratio_threshold(pitch, config) else "missed"
            pitch_decisions.append((pitch, decision, confidence, exact_ratio))
        # Known before the wrong_pitch fallback runs, so it never re-proposes a
        # pitch this same chord event already confirmed via another member --
        # e.g. a chord's unconfirmed lower note shouldn't get "explained" as a
        # duplicate of the chord's own (already-matched) upper note.
        expected_pitches_this_event = {p for p, d, _c, _r in pitch_decisions if d == "expected_pitch"}

        wrong_pitch_emitted = False
        for pitch, decision, confidence, exact_ratio in pitch_decisions:
            emit_pitch = pitch if decision == "expected_pitch" else None
            if (
                decision != "expected_pitch"
                and config.emit_wrong_pitch
                and not wrong_pitch_emitted
            ):
                winner, winner_confidence = _onset_full_winner(pos_onset)
                if (
                    winner is not None
                    and winner_confidence >= config.min_winner_confidence
                    and winner not in expected_pitches_this_event
                ):
                    decision = "wrong_pitch_candidate"
                    emit_pitch = winner
                    wrong_pitch_emitted = True
            debug_notes.append({
                "pitch": pitch, "matched_onset_sec": round(onset_sec, 4),
                "confidence": round(confidence, 4), "ref_ratio": round(exact_ratio, 4),
                "decision": decision,
            })
            if emit_pitch is not None:
                performance.append({
                    "pitch": int(emit_pitch),
                    "onset_sec": round(float(onset_sec), 6),
                    "dur_sec": 0.18,
                    "velocity": 80,
                })

    # Onsets DTW didn't match to any reference event: still worth checking
    # with the open-ended (whole-keyboard-candidate) onset-first scoring, so a
    # genuinely wrong/extra note the student played still surfaces as `extra`
    # instead of silently vanishing just because no reference event wanted it.
    for j, onset_info in enumerate(onset_frames):
        if j in matched_onset_indices or _below_floor(onset_info["energy"]):
            continue
        candidates = _candidate_pitches(config)
        scores = {c: score_candidate(onset_info["frame"], c, c, candidates, verifier_config) for c in candidates}
        total = float(sum(scores.values()))
        pitches = _select_onset_pitches(scores, total, config)
        for pitch in pitches:
            performance.append({
                "pitch": int(pitch),
                "onset_sec": round(float(onset_info["onset_sec"]), 6),
                "dur_sec": 0.18,
                "velocity": 80,
            })
        if pitches:
            debug_notes.append({
                "onset_sec": round(onset_info["onset_sec"], 4),
                "selected_pitches": pitches, "decision": "unmatched_onset_extra",
            })

    performance.sort(key=lambda n: n["onset_sec"])
    debug = {
        "mode": "reference_dtw",
        "detected_onsets": len(onset_times),
        "reference_events": len(ref_events),
        "emitted_notes": len(performance),
        "energy_floor": round(energy_floor, 6),
        "notes": debug_notes,
    }
    return performance, debug


def load_profile_if_present(path: Optional[str]) -> Optional[dict]:
    return load_keyboard_profile(path) if path else None
