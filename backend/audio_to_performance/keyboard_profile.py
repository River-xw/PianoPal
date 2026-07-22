"""Train a lightweight keyboard timbre profile from recordings.

This is deliberately not a neural-network training path. For a cheap
electronic keyboard, a small spectral profile is often more useful: estimate
stable pitched frames, group them by MIDI note, and store the harmonic energy
shape seen for each pitch. That profile can later be used as an extra evidence
source in constrained verification.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import librosa
import numpy as np

from backend.hardware import KEYBOARD_RANGE


TARGET_SR = 44100


@dataclass
class KeyboardProfileTrainingConfig:
    keyboard_range: Optional[tuple[int, int]] = KEYBOARD_RANGE
    target_sr: int = TARGET_SR
    frame_length: int = 4096
    hop_length: int = 512
    max_harmonic: int = 10
    min_note_frames: int = 8
    max_pitch_deviation_semitones: float = 0.35
    active_rms_percentile: float = 55.0


def _midi_to_hz(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


def _energy_at_hz(magnitude_frame: np.ndarray, freqs: np.ndarray, hz: float) -> float:
    if hz <= 0 or hz >= freqs[-1]:
        return 0.0
    idx = int(np.argmin(np.abs(freqs - hz)))
    return float(magnitude_frame[idx])


def _frame_harmonics(
    magnitude_frame: np.ndarray,
    freqs: np.ndarray,
    midi_pitch: int,
    max_harmonic: int,
) -> np.ndarray:
    f0 = _midi_to_hz(midi_pitch)
    values = np.array([
        _energy_at_hz(magnitude_frame, freqs, f0 * harmonic)
        for harmonic in range(1, max_harmonic + 1)
    ], dtype=np.float64)
    total = float(values.sum())
    if total <= 0:
        return values
    return values / total


def train_keyboard_profile(
    audio_paths: Iterable[str],
    config: Optional[KeyboardProfileTrainingConfig] = None,
) -> dict:
    """Build a lightweight spectral profile from one or more recordings.

    The recordings do not need note labels. The trainer uses pYIN to find
    stable pitched frames, rounds them to MIDI notes, filters impossible
    pitches, then averages harmonic energy ratios per note.
    """
    config = config or KeyboardProfileTrainingConfig()
    paths = [str(Path(p)) for p in audio_paths]
    if not paths:
        raise ValueError("at least one audio path is required")

    low_pitch, high_pitch = config.keyboard_range if config.keyboard_range else (0, 127)
    fmin = _midi_to_hz(low_pitch)
    fmax = _midi_to_hz(high_pitch)

    accum: dict[int, list[np.ndarray]] = {}
    file_stats = []
    total_candidate_frames = 0
    total_kept_frames = 0

    for path in paths:
        audio, sr = librosa.load(path, sr=config.target_sr, mono=True)
        if len(audio) == 0:
            file_stats.append({"path": path, "duration_sec": 0.0, "kept_frames": 0})
            continue

        rms = librosa.feature.rms(
            y=audio,
            frame_length=config.frame_length,
            hop_length=config.hop_length,
        )[0]
        active_threshold = float(np.percentile(rms, config.active_rms_percentile))
        f0, _, _ = librosa.pyin(
            audio,
            fmin=fmin,
            fmax=fmax,
            sr=sr,
            frame_length=config.frame_length,
            hop_length=config.hop_length,
        )
        stft = np.abs(librosa.stft(
            audio,
            n_fft=config.frame_length,
            hop_length=config.hop_length,
            window="hann",
        ))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=config.frame_length)

        kept = 0
        usable_frames = min(len(f0), stft.shape[1], len(rms))
        for frame_idx in range(usable_frames):
            if np.isnan(f0[frame_idx]) or rms[frame_idx] < active_threshold:
                continue
            midi_float = float(librosa.hz_to_midi(f0[frame_idx]))
            midi_pitch = int(round(midi_float))
            total_candidate_frames += 1
            if not (low_pitch <= midi_pitch <= high_pitch):
                continue
            if abs(midi_float - midi_pitch) > config.max_pitch_deviation_semitones:
                continue

            harmonic_vector = _frame_harmonics(
                stft[:, frame_idx],
                freqs,
                midi_pitch,
                config.max_harmonic,
            )
            if harmonic_vector.sum() <= 0:
                continue
            accum.setdefault(midi_pitch, []).append(harmonic_vector)
            kept += 1
            total_kept_frames += 1

        file_stats.append({
            "path": path,
            "duration_sec": round(len(audio) / sr, 4),
            "kept_frames": kept,
        })

    notes = {}
    for pitch, vectors in sorted(accum.items()):
        if len(vectors) < config.min_note_frames:
            continue
        matrix = np.vstack(vectors)
        mean = matrix.mean(axis=0)
        std = matrix.std(axis=0)
        notes[str(pitch)] = {
            "midi": pitch,
            "frequency_hz": round(_midi_to_hz(pitch), 4),
            "frames": int(len(vectors)),
            "harmonic_energy_mean": [round(float(v), 6) for v in mean],
            "harmonic_energy_std": [round(float(v), 6) for v in std],
        }

    return {
        "schema": "pianopal.keyboard_profile.v1",
        "training_method": "pyin_stable_frame_harmonic_average",
        "source_files": paths,
        "sample_rate": config.target_sr,
        "keyboard_range": [low_pitch, high_pitch],
        "max_harmonic": config.max_harmonic,
        "config": {
            "frame_length": config.frame_length,
            "hop_length": config.hop_length,
            "min_note_frames": config.min_note_frames,
            "max_pitch_deviation_semitones": config.max_pitch_deviation_semitones,
            "active_rms_percentile": config.active_rms_percentile,
        },
        "summary": {
            "files": len(paths),
            "candidate_frames": total_candidate_frames,
            "kept_frames": total_kept_frames,
            "profiled_notes": len(notes),
            "profiled_midi_pitches": [int(p) for p in notes.keys()],
        },
        "files": file_stats,
        "notes": notes,
    }
