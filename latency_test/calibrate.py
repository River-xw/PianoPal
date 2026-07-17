"""Measures end-to-end system latency: speaker -> air -> microphone -> onset
detection. Synthesizes a click track with precisely known click times, plays
it and records it in the SAME audio stream (sd.playrec, not separate play()
+ record() calls -- that would add unknown OS-scheduling skew between the
two operations and contaminate the measurement), then runs onset detection
on the recording and compares detected onset times to the true click times.

Device-agnostic by design: the microphone used for this proof-of-concept
run (a laptop's built-in mic) is NOT the microphone the real AIoT rig will
use. Point --input-device at whatever mic is actually connected (use
--list-devices to find its ID/name) and rerun -- the number this produces
is specific to that exact hardware chain (mic capsule + audio interface +
drivers), so it must be re-measured whenever the hardware changes.

This number matters for the real deployment: any onset the AIoT sound
sensor detects is this many ms *behind* when the note was actually struck,
so it should be subtracted (or accounted for) before comparing a live
performance's timing against the score_to_reference ground truth.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import librosa
import numpy as np
import sounddevice as sd
import soundfile as sf

SAMPLE_RATE = 44100
CLICK_FREQ_HZ = 2000
CLICK_DURATION_SEC = 0.005
LEAD_IN_SEC = 1.0
MATCH_WINDOW_SEC = 0.25


@dataclass
class CalibrationResult:
    true_times: np.ndarray
    detected_times: np.ndarray  # NaN where no onset matched within the window
    offsets_ms: np.ndarray  # detected - true, only for matched clicks


def list_devices() -> None:
    print(sd.query_devices())
    print("\n(輸入編號給 --input-device / --output-device，或直接給名稱關鍵字也可以)")


def resolve_device(spec: str | None):
    if spec is None:
        return None
    try:
        return int(spec)
    except ValueError:
        return spec  # sounddevice also accepts a name substring


def device_label(spec) -> str:
    try:
        return sd.query_devices(spec)["name"]
    except Exception:
        return "系統預設"


def generate_click_track(num_clicks: int, interval_sec: float, sr: int = SAMPLE_RATE):
    total_duration = LEAD_IN_SEC + interval_sec * num_clicks + interval_sec
    track = np.zeros(int(total_duration * sr), dtype=np.float32)
    true_times = []
    for i in range(num_clicks):
        t = LEAD_IN_SEC + interval_sec * i
        true_times.append(t)
        start = int(t * sr)
        n = int(CLICK_DURATION_SEC * sr)
        # short tone burst with a fast attack -- easy for a generic onset
        # detector to pick up precisely (no slow fade-in to blur the edge)
        tone = np.sin(2 * np.pi * CLICK_FREQ_HZ * np.arange(n) / sr).astype(np.float32)
        window = np.ones(n, dtype=np.float32)
        window[-int(n * 0.3):] *= np.linspace(1, 0, int(n * 0.3))  # only taper the tail
        track[start:start + n] = tone * window
    return track, np.array(true_times)


def play_and_record(track: np.ndarray, sr: int, input_device, output_device) -> np.ndarray:
    device = None
    if input_device is not None or output_device is not None:
        device = (input_device, output_device)
    recording = sd.playrec(track.reshape(-1, 1), samplerate=sr, channels=1, dtype="float32", device=device)
    sd.wait()
    return recording.flatten()


def match_onsets(true_times: np.ndarray, detected_times: np.ndarray) -> CalibrationResult:
    matched_detected = np.full(len(true_times), np.nan)
    used = set()
    for i, t in enumerate(true_times):
        candidates = [(abs(d - t), j, d) for j, d in enumerate(detected_times)
                      if j not in used and abs(d - t) < MATCH_WINDOW_SEC]
        if candidates:
            _, j, d = min(candidates)
            matched_detected[i] = d
            used.add(j)
    offsets_ms = (matched_detected - true_times) * 1000.0
    return CalibrationResult(true_times, matched_detected, offsets_ms[~np.isnan(offsets_ms)])


def robust_outlier_mask(offsets_ms: np.ndarray, mad_threshold: float = 3.0) -> np.ndarray:
    """True where a value is a likely spurious match (e.g. background noise
    picked up as a false onset) -- flagged via median absolute deviation
    rather than mean/std, since a single bad match otherwise skews both.
    """
    if len(offsets_ms) < 3:
        return np.zeros(len(offsets_ms), dtype=bool)
    median = np.median(offsets_ms)
    mad = np.median(np.abs(offsets_ms - median)) or 1e-9
    return np.abs(offsets_ms - median) / mad > mad_threshold


def run_calibration(
    num_clicks: int,
    interval_sec: float,
    save_wav: str | None = None,
    save_result: str | None = None,
    input_device=None,
    output_device=None,
) -> CalibrationResult:
    input_name = device_label(input_device)
    output_name = device_label(output_device)
    print(f"輸入裝置(麥克風): {input_name}")
    print(f"輸出裝置(喇叭): {output_name}")

    track, true_times = generate_click_track(num_clicks, interval_sec)

    print(f"播放 {num_clicks} 個 click（間隔 {interval_sec}s）並同時錄音...")
    recording = play_and_record(track, SAMPLE_RATE, input_device, output_device)

    if save_wav:
        sf.write(save_wav, recording, SAMPLE_RATE)
        print(f"錄音已存到 {save_wav}")

    onset_times = librosa.onset.onset_detect(
        y=recording, sr=SAMPLE_RATE, units="time", backtrack=False
    )

    result = match_onsets(true_times, onset_times)
    matched = ~np.isnan(result.detected_times)

    latency_ms = jitter_ms = None
    outlier_count = 0

    print(f"\n偵測到 {matched.sum()}/{len(true_times)} 個 click")
    if len(result.offsets_ms):
        outlier = robust_outlier_mask(result.offsets_ms)
        clean = result.offsets_ms[~outlier]
        outlier_count = int(outlier.sum())
        latency_ms, jitter_ms = float(clean.mean()), float(clean.std())

        print(f"平均延遲(含離群值): {result.offsets_ms.mean():.1f} ms，標準差: {result.offsets_ms.std():.1f} ms")
        if outlier_count:
            print(f"偵測到 {outlier_count} 個離群值(可能是背景雜音誤觸發，不是真的 click)，已排除")
            print(f"排除後延遲: {latency_ms:.1f} ms，標準差(jitter): {jitter_ms:.1f} ms  <- 這個數字比較可信")
        else:
            print("沒有離群值，延遲數字可直接採用")
        print(f"最小/最大(排除離群值後): {clean.min():.1f} / {clean.max():.1f} ms")
    else:
        print("沒有任何 click 被成功比對到 -- 麥克風可能沒收到音量，或偵測門檻不合適")

    print("\n逐一比對：")
    for i, t in enumerate(result.true_times):
        d = result.detected_times[i]
        if np.isnan(d):
            print(f"  click {i}: 真實時間 {t:.3f}s -> 沒偵測到")
        else:
            print(f"  click {i}: 真實時間 {t:.3f}s -> 偵測到 {d:.3f}s (offset {(d - t) * 1000:+.1f}ms)")

    if save_result:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input_device": input_name,
            "output_device": output_name,
            "num_clicks": num_clicks,
            "matched": int(matched.sum()),
            "outliers_excluded": outlier_count,
            "latency_ms": latency_ms,
            "jitter_ms": jitter_ms,
            "raw_offsets_ms": result.offsets_ms.tolist(),
        }
        with open(save_result, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"\n校準結果已存到 {save_result}（給之後套用延遲修正用）")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="麥克風收音延遲校準")
    parser.add_argument("--clicks", type=int, default=10, help="click 數量")
    parser.add_argument("--interval", type=float, default=1.0, help="click 間隔秒數")
    parser.add_argument("--save-wav", default=None, help="把錄到的音檔存成 wav 方便除錯")
    parser.add_argument("--save-result", default=None, help="把校準結果(延遲/jitter/裝置資訊)存成 json")
    parser.add_argument("--input-device", default=None, help="麥克風裝置(數字ID或名稱關鍵字)，不指定用系統預設")
    parser.add_argument("--output-device", default=None, help="喇叭裝置(數字ID或名稱關鍵字)，不指定用系統預設")
    parser.add_argument("--list-devices", action="store_true", help="列出可用的音訊裝置後結束")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return 0

    run_calibration(
        args.clicks, args.interval,
        save_wav=args.save_wav, save_result=args.save_result,
        input_device=resolve_device(args.input_device),
        output_device=resolve_device(args.output_device),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
