"""Sample keybank utilities for the BF-3738C white-key workflow."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import librosa
import numpy as np
import soundfile as sf

from backend.hardware import KEYBOARD_HIGHEST_PITCH, KEYBOARD_LOWEST_PITCH

from .keyboard_profile import _frame_harmonics, _midi_to_hz


TARGET_SR = 44100
WHITE_KEY_MIDIS = tuple(
    pitch
    for pitch in range(KEYBOARD_LOWEST_PITCH, KEYBOARD_HIGHEST_PITCH + 1)
    if pitch % 12 in {0, 2, 4, 5, 7, 9, 11}
)


@dataclass
class ScaleKeybankTrainingConfig:
    target_sr: int = TARGET_SR
    frame_length: int = 4096
    hop_length: int = 512
    max_harmonic: int = 10
    min_onset_gap_sec: float = 0.9
    onset_delta: float = 0.08
    sample_pre_roll_sec: float = 0.03
    sample_guard_before_next_sec: float = 0.12
    min_sample_sec: float = 0.45
    max_sample_sec: float = 1.45
    tail_rms_ratio: float = 0.16
    tail_floor_percentile: float = 35.0
    fade_sec: float = 0.005
    normalize_peak: float = 0.75
    attack_refine_window_sec: float = 0.8
    attack_refine_ratio: float = 0.3
    attack_refine_min_shift_sec: float = 0.15


def midi_to_name(pitch: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    octave = pitch // 12 - 1
    return f"{names[pitch % 12]}{octave}"


def expected_midis_for_keys(keys: str) -> tuple[int, ...]:
    if keys != "white":
        raise ValueError("only keys='white' is implemented; record black keys separately later")
    return WHITE_KEY_MIDIS


def _merge_close_onsets(onsets: Iterable[float], min_gap_sec: float) -> list[float]:
    merged: list[float] = []
    for onset in onsets:
        onset = float(onset)
        if not merged or onset - merged[-1] >= min_gap_sec:
            merged.append(onset)
    return merged


def detect_scale_onsets(
    audio: np.ndarray,
    sr: int,
    expected_count: int,
    config: ScaleKeybankTrainingConfig,
) -> tuple[list[float], dict]:
    onset_env = librosa.onset.onset_strength(y=audio, sr=sr, hop_length=config.hop_length)
    frames = librosa.onset.onset_detect(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=config.hop_length,
        units="frames",
        backtrack=True,
        pre_max=3,
        post_max=8,
        pre_avg=12,
        post_avg=24,
        delta=config.onset_delta,
        wait=16,
    )
    raw_onsets = [float(t) for t in librosa.frames_to_time(frames, sr=sr, hop_length=config.hop_length)]
    merged = _merge_close_onsets(raw_onsets, config.min_onset_gap_sec)
    if len(merged) < expected_count:
        raise ValueError(
            f"detected only {len(merged)} note onsets after de-duplication; "
            f"expected {expected_count}. Try lowering --onset-delta or --min-onset-gap-sec."
        )
    used = merged[:expected_count]
    return used, {
        "raw_onsets": [round(t, 6) for t in raw_onsets],
        "raw_onset_count": len(raw_onsets),
        "deduplicated_onsets": [round(t, 6) for t in merged],
        "deduplicated_onset_count": len(merged),
        "used_onsets": [round(t, 6) for t in used],
        "dropped_extra_onsets": max(0, len(merged) - expected_count),
    }


def _clip_end_from_rms(
    audio: np.ndarray,
    sr: int,
    onset_sec: float,
    hard_end_sec: float,
    rms: np.ndarray,
    rms_times: np.ndarray,
    config: ScaleKeybankTrainingConfig,
) -> float:
    if hard_end_sec <= onset_sec:
        return min(len(audio) / sr, onset_sec + config.min_sample_sec)

    mask = (rms_times >= onset_sec + 0.08) & (rms_times <= hard_end_sec)
    if not np.any(mask):
        return hard_end_sec

    local_rms = rms[mask]
    local_peak = float(local_rms.max()) if len(local_rms) else 0.0
    if local_peak <= 0:
        return hard_end_sec

    floor = float(np.percentile(rms, config.tail_floor_percentile))
    threshold = max(floor * 1.2, local_peak * config.tail_rms_ratio)
    frame_indices = np.where(mask)[0]
    active_indices = frame_indices[rms[frame_indices] >= threshold]
    if len(active_indices) == 0:
        return hard_end_sec

    rms_end = float(rms_times[active_indices[-1]]) + 0.08
    min_end = onset_sec + config.min_sample_sec
    return min(hard_end_sec, max(min_end, rms_end))


def _refine_onset_to_true_attack(
    onset_sec: float,
    next_onset_sec: float,
    rms: np.ndarray,
    rms_times: np.ndarray,
    config: ScaleKeybankTrainingConfig,
) -> tuple[float, bool]:
    """Onset detection occasionally locks onto a spurious quiet blip (hand
    noise, key-release bleed from the previous note) instead of the actual
    strike. _merge_close_onsets always keeps whichever onset came first, so
    when the real strike follows within min_onset_gap_sec it gets silently
    discarded, and the sample would be clipped starting on near-silence with
    the true tone only appearing several hundred ms later -- audible as a
    note that comes in "late" relative to others it should be simultaneous
    with. Re-check a window after the assigned onset for a much stronger
    peak; if the assigned onset itself sits far below that peak, walk back
    from the peak to where the real attack rises and use that instead.
    """
    search_end = min(next_onset_sec, onset_sec + config.attack_refine_window_sec)
    mask = (rms_times >= onset_sec) & (rms_times <= search_end)
    if not np.any(mask):
        return onset_sec, False

    window_rms = rms[mask]
    window_times = rms_times[mask]
    peak = float(window_rms.max())
    if peak <= 0:
        return onset_sec, False

    threshold = config.attack_refine_ratio * peak
    if float(window_rms[0]) >= threshold:
        return onset_sec, False  # onset already sits on/near the real attack

    peak_idx = int(np.argmax(window_rms))
    rise_idx = peak_idx
    while rise_idx > 0 and window_rms[rise_idx - 1] >= threshold:
        rise_idx -= 1
    corrected = float(window_times[rise_idx])
    # a normal percussive attack ramps up over ~10-30ms even when the onset
    # is correctly detected -- only treat this as a genuine mis-detection
    # (onset locked onto an earlier spurious blip) when the real attack is
    # substantially later, not just windowing/ramp noise around the threshold
    if corrected - onset_sec < config.attack_refine_min_shift_sec:
        return onset_sec, False
    return corrected, True


def _fade_and_normalize(sample: np.ndarray, sr: int, config: ScaleKeybankTrainingConfig) -> np.ndarray:
    out = np.array(sample, dtype=np.float32, copy=True)
    if len(out) == 0:
        return out
    fade_len = min(int(config.fade_sec * sr), len(out) // 2)
    if fade_len > 1:
        fade_in = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)
        fade_out = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
        out[:fade_len] *= fade_in
        out[-fade_len:] *= fade_out
    peak = float(np.max(np.abs(out)))
    if config.normalize_peak > 0 and peak > 1e-8:
        out = out * (config.normalize_peak / peak)
    return np.clip(out, -1.0, 1.0)


def _harmonic_stats(
    audio: np.ndarray,
    sr: int,
    midi_pitch: int,
    config: ScaleKeybankTrainingConfig,
) -> tuple[list[float], list[float], int]:
    if len(audio) < config.frame_length // 2:
        return [], [], 0
    stft = np.abs(librosa.stft(
        audio,
        n_fft=config.frame_length,
        hop_length=config.hop_length,
        window="hann",
    ))
    if stft.shape[1] == 0:
        return [], [], 0
    rms = librosa.feature.rms(
        y=audio,
        frame_length=config.frame_length,
        hop_length=config.hop_length,
    )[0]
    freqs = librosa.fft_frequencies(sr=sr, n_fft=config.frame_length)
    threshold = max(float(np.percentile(rms, 35)) * 1.2, float(np.max(rms)) * 0.12)
    vectors = []
    for frame_idx in range(min(len(rms), stft.shape[1])):
        if rms[frame_idx] < threshold:
            continue
        vector = _frame_harmonics(stft[:, frame_idx], freqs, midi_pitch, config.max_harmonic)
        if vector.sum() > 0:
            vectors.append(vector)
    if not vectors:
        return [], [], 0
    matrix = np.vstack(vectors)
    return (
        [round(float(v), 6) for v in matrix.mean(axis=0)],
        [round(float(v), 6) for v in matrix.std(axis=0)],
        int(len(vectors)),
    )


def _pyin_median_midi(
    audio: np.ndarray,
    sr: int,
    config: ScaleKeybankTrainingConfig,
) -> Optional[float]:
    if len(audio) < config.frame_length:
        return None
    # librosa.pyin loses track near the edges of its own search window (no room
    # for its internal candidate grid to resolve a pitch sitting exactly at
    # fmin/fmax), which was previously flagging the keyboard's own top note as
    # a false-positive octave disagreement. Pad the search range a few
    # semitones beyond the keyboard's physical range so this is a genuine
    # sanity check on the played note, not an artifact of the boundary.
    edge_margin_semitones = 4
    f0, _, _ = librosa.pyin(
        audio,
        fmin=_midi_to_hz(KEYBOARD_LOWEST_PITCH - edge_margin_semitones),
        fmax=_midi_to_hz(KEYBOARD_HIGHEST_PITCH + edge_margin_semitones),
        sr=sr,
        frame_length=config.frame_length,
        hop_length=config.hop_length,
    )
    voiced = f0[~np.isnan(f0)]
    if len(voiced) == 0:
        return None
    return float(np.median(librosa.hz_to_midi(voiced)))


def train_keybank_from_scale(
    audio_path: str,
    output_path: str,
    samples_dir: str,
    keys: str = "white",
    config: Optional[ScaleKeybankTrainingConfig] = None,
) -> dict:
    """Train a left-to-right scale keybank and write sample clips.

    The note labels come from the known physical key order. This is important
    for toy-keyboard tones where generic pitch trackers often lock onto an
    octave harmonic instead of the played key.
    """
    config = config or ScaleKeybankTrainingConfig()
    expected_midis = expected_midis_for_keys(keys)
    audio, sr = librosa.load(audio_path, sr=config.target_sr, mono=True)
    output = Path(output_path)
    sample_root = Path(samples_dir)
    sample_root.mkdir(parents=True, exist_ok=True)

    onsets, onset_debug = detect_scale_onsets(audio, sr, len(expected_midis), config)
    rms = librosa.feature.rms(y=audio, frame_length=2048, hop_length=config.hop_length)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=config.hop_length)

    sample_entries = []
    profile_notes = {}
    duration_sec = len(audio) / sr
    onsets_corrected = 0
    used_onsets_final = []
    for idx, (onset_sec, midi_pitch) in enumerate(zip(onsets, expected_midis), start=1):
        next_onset_sec = onsets[idx] if idx < len(onsets) else duration_sec
        onset_sec, onset_was_corrected = _refine_onset_to_true_attack(
            onset_sec, next_onset_sec, rms, rms_times, config,
        )
        if onset_was_corrected:
            onsets_corrected += 1
        used_onsets_final.append(onset_sec)
        hard_end_sec = min(
            duration_sec,
            next_onset_sec - config.sample_guard_before_next_sec,
            onset_sec + config.max_sample_sec,
        )
        start_sec = max(0.0, onset_sec - config.sample_pre_roll_sec)
        end_sec = _clip_end_from_rms(audio, sr, onset_sec, hard_end_sec, rms, rms_times, config)
        end_sec = min(duration_sec, max(end_sec, start_sec + config.min_sample_sec))
        start_sample = max(0, int(round(start_sec * sr)))
        end_sample = min(len(audio), int(round(end_sec * sr)))
        raw_sample = np.array(audio[start_sample:end_sample], dtype=np.float32)
        saved_sample = _fade_and_normalize(raw_sample, sr, config)

        name = midi_to_name(midi_pitch)
        filename = f"{idx:02d}_{name.replace('#', 's')}_{midi_pitch}.wav"
        sample_path = sample_root / filename
        sf.write(sample_path, saved_sample, sr)

        harmonic_mean, harmonic_std, harmonic_frames = _harmonic_stats(raw_sample, sr, midi_pitch, config)
        pyin_midi = _pyin_median_midi(raw_sample, sr, config)
        original_peak = float(np.max(np.abs(raw_sample))) if len(raw_sample) else 0.0
        original_rms = float(np.sqrt(np.mean(np.square(raw_sample)))) if len(raw_sample) else 0.0
        diagnostic_flags = []
        if pyin_midi is not None and abs(pyin_midi - midi_pitch) > 0.75:
            diagnostic_flags.append("pyin_octave_or_pitch_disagrees_with_order_label")
        if onset_was_corrected:
            diagnostic_flags.append("onset_corrected_to_true_attack")

        entry = {
            "key_index": idx,
            "midi": int(midi_pitch),
            "name": name,
            "frequency_hz": round(_midi_to_hz(midi_pitch), 4),
            "start_sec": round(float(start_sec), 6),
            "end_sec": round(float(end_sec), 6),
            "duration_sec": round(float(end_sec - start_sec), 6),
            "sample_path": str(sample_path),
            "original_peak": round(original_peak, 6),
            "original_rms": round(original_rms, 6),
            "pyin_median_midi": round(pyin_midi, 4) if pyin_midi is not None else None,
            "harmonic_frames": harmonic_frames,
            "harmonic_energy_mean": harmonic_mean,
            "harmonic_energy_std": harmonic_std,
            "diagnostic_flags": diagnostic_flags,
        }
        sample_entries.append(entry)
        if harmonic_mean:
            profile_notes[str(midi_pitch)] = {
                "midi": int(midi_pitch),
                "frequency_hz": round(_midi_to_hz(midi_pitch), 4),
                "frames": harmonic_frames,
                "harmonic_energy_mean": harmonic_mean,
                "harmonic_energy_std": harmonic_std,
            }

    profile = {
        "schema": "pianopal.keyboard_profile.v1",
        "training_method": "ordered_scale_keybank_harmonic_average",
        "source_files": [str(audio_path)],
        "sample_rate": sr,
        "keyboard_range": [int(expected_midis[0]), int(expected_midis[-1])],
        "allowed_midi_pitches": [int(p) for p in expected_midis],
        "max_harmonic": config.max_harmonic,
        "summary": {
            "files": 1,
            "candidate_frames": sum(int(e["harmonic_frames"]) for e in sample_entries),
            "kept_frames": sum(int(e["harmonic_frames"]) for e in sample_entries),
            "profiled_notes": len(profile_notes),
            "profiled_midi_pitches": [int(p) for p in profile_notes.keys()],
        },
        "notes": profile_notes,
    }
    keybank = {
        "schema": "pianopal.keybank.v1",
        "training_method": "ordered_left_to_right_scale_segmentation",
        "source_audio": str(audio_path),
        "sample_rate": sr,
        "keys": keys,
        "expected_midi_pitches": [int(p) for p in expected_midis],
        "samples_dir": str(sample_root),
        "config": {
            "min_onset_gap_sec": config.min_onset_gap_sec,
            "onset_delta": config.onset_delta,
            "sample_pre_roll_sec": config.sample_pre_roll_sec,
            "sample_guard_before_next_sec": config.sample_guard_before_next_sec,
            "min_sample_sec": config.min_sample_sec,
            "max_sample_sec": config.max_sample_sec,
            "tail_rms_ratio": config.tail_rms_ratio,
            "normalize_peak": config.normalize_peak,
        },
        "onset_detection": {
            **onset_debug,
            "used_onsets": [round(t, 6) for t in used_onsets_final],
            "onsets_corrected_to_true_attack": onsets_corrected,
        },
        "summary": {
            "sample_count": len(sample_entries),
            "diagnostic_flag_count": sum(len(e["diagnostic_flags"]) for e in sample_entries),
            "diagnostic_flags": sorted({flag for e in sample_entries for flag in e["diagnostic_flags"]}),
        },
        "samples": sample_entries,
        "keyboard_profile": profile,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(keybank, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return keybank


def load_keybank(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def keybank_profile(keybank: dict) -> dict:
    return keybank["keyboard_profile"]
