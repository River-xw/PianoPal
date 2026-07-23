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
        elif ref_score > 0 and ref_ratio >= config.min_ref_score_ratio and confidence >= config.min_winner_confidence:
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


def load_profile_if_present(path: Optional[str]) -> Optional[dict]:
    return load_keyboard_profile(path) if path else None
