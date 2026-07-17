"""Validates the *scoring engine itself* against real microphone audio,
not synthetic clicks: records you tapping a steady beat, detects onsets,
corrects for the measured system latency (see calibrate.py), builds an
idealized steady-pulse reference from your own average tap interval, and
scores your tapping against it through the real scoring.score_performance()
pipeline. This is Phase 2 of the two calibration steps -- Phase 1
(calibrate.py) measures pipeline latency using a known synthetic signal;
this measures whether the whole pipeline gives sensible results on a real,
noisy, human-timed signal.

Pitch is irrelevant here (a tap/clap has no determinate pitch), so both the
synthetic reference and the detected performance are given the same dummy
pitch -- every note always "matches" on pitch, isolating the test to pure
timing/rhythm accuracy.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from latency_test.onset_utils import detect_onsets  # noqa: E402
from scoring import ScoringConfig, score_performance  # noqa: E402

SAMPLE_RATE = 44100
DUMMY_PITCH = 60
COUNT_IN_BEEPS = 3
COUNT_IN_INTERVAL_SEC = 0.6


def _beep(freq_hz: float, duration_sec: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    n = int(duration_sec * sr)
    tone = np.sin(2 * np.pi * freq_hz * np.arange(n) / sr).astype(np.float32)
    tone[-int(n * 0.2):] *= np.linspace(1, 0, int(n * 0.2))
    return tone


def count_in(input_device=None, output_device=None) -> None:
    beep = _beep(1500, 0.08)
    gap = np.zeros(int(COUNT_IN_INTERVAL_SEC * SAMPLE_RATE) - len(beep), dtype=np.float32)
    track = np.concatenate([np.concatenate([beep, gap]) for _ in range(COUNT_IN_BEEPS)])
    device = (input_device, output_device) if (input_device or output_device) else None
    sd.play(track, samplerate=SAMPLE_RATE, device=output_device if device is None else device[1])
    sd.wait()


def record_taps(duration_sec: float, input_device=None) -> np.ndarray:
    recording = sd.rec(
        int(duration_sec * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1,
        dtype="float32", device=input_device,
    )
    sd.wait()
    return recording.flatten()




def build_ideal_reference(onset_times: np.ndarray) -> dict:
    """Idealized perfectly-steady pulse at the mean interval of the actual
    taps -- this is *not* an externally-known ground truth (the user tapped
    freely, at their own chosen pace), it's the best-fit steady tempo
    against which we measure how *consistent* the tapping was.
    """
    intervals = np.diff(onset_times)
    mean_interval = float(np.mean(intervals))
    bpm = 60.0 / mean_interval

    notes = []
    for i, t in enumerate(onset_times):
        onset_beats = float(i)
        notes.append({
            "pitch": DUMMY_PITCH, "name": "tap",
            "onset_beats": onset_beats, "onset_sec": onset_beats * mean_interval,
            "dur_beats": 1.0, "dur_sec": mean_interval,
            "velocity": 80, "hand": "R", "measure": i + 1,
        })
    return {
        "title": "Ideal steady pulse (fit from your own tapping)",
        "tempo_bpm": round(bpm), "tempo_map": [{"beat": 0.0, "bpm": bpm}],
        "time_signature": "4/4", "key": "C major",
        "duration_beats": float(len(notes)), "duration_sec": float(len(notes) * mean_interval),
        "notes": notes,
    }


def run_rhythm_test(
    num_taps: int, duration_sec: float, latency_ms: float,
    input_device=None, output_device=None, save_wav: str | None = None,
):
    print(f"倒數 {COUNT_IN_BEEPS} 拍之後，請照著自己覺得穩定的速度，拍打/拍手 {num_taps} 下")
    print("準備...")
    time.sleep(1)
    count_in(input_device, output_device)

    print(f"開始錄音（{duration_sec:.1f} 秒）-- 現在開始拍打！")
    recording = record_taps(duration_sec, input_device)
    print("錄音結束")

    if save_wav:
        sf.write(save_wav, recording, SAMPLE_RATE)
        print(f"錄音已存到 {save_wav}")

    raw_onsets = detect_onsets(recording, SAMPLE_RATE)
    # drop anything inside/near the count-in window (those are the beeps, not taps)
    count_in_end = COUNT_IN_BEEPS * COUNT_IN_INTERVAL_SEC
    onsets = raw_onsets[raw_onsets > count_in_end + 0.15]

    print(f"\n偵測到 {len(onsets)} 個拍點（預期 {num_taps} 個）")
    if len(onsets) < 3:
        print("拍點太少，沒辦法算出穩定的參考節拍，重跑一次試試看")
        return None

    # correct for measured system latency before anything else touches these times
    corrected_onsets = onsets - (latency_ms / 1000.0)

    reference = build_ideal_reference(corrected_onsets)
    performance = [
        {"pitch": DUMMY_PITCH, "onset_sec": float(t), "dur_sec": 0.1, "velocity": 80}
        for t in corrected_onsets
    ]

    result = score_performance(reference, performance, ScoringConfig())

    print(f"\n擬合出的穩定節拍: {reference['tempo_bpm']} bpm")
    print(f"總分: {result.summary.score}")
    print(f"子分數: {result.summary.sub_scores}")
    print(f"節奏穩定度: {result.summary.sub_scores['timing_stability']}  <- 這個數字反映你拍打的穩定度")
    print(f"tempo_trend: {result.summary.tempo_trend}")
    print(f"計數: {result.summary.counts}")

    offsets = [n.offset_ms for n in result.notes if n.offset_ms is not None]
    if offsets:
        print(f"\n每拍偏差(ms，相對於你自己的平均節奏): {[round(o, 1) for o in offsets]}")

    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="用真人拍打驗證 scoring 引擎的拍子準確度分析")
    parser.add_argument("--taps", type=int, default=8, help="要拍幾下")
    parser.add_argument("--duration", type=float, default=8.0, help="錄音時長(秒)，要夠長裝下所有拍點")
    parser.add_argument("--latency-ms", type=float, default=132.4,
                         help="calibrate.py 測出來的系統延遲，會從偵測到的時間裡扣掉")
    parser.add_argument("--input-device", default=None)
    parser.add_argument("--output-device", default=None)
    parser.add_argument("--save-wav", default=None)
    args = parser.parse_args()

    run_rhythm_test(
        args.taps, args.duration, args.latency_ms,
        input_device=args.input_device, output_device=args.output_device,
        save_wav=args.save_wav,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
