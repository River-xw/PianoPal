"""Record a live microphone take of a real performance (e.g. playing a
YouTube video of someone performing a piece we have a reference for),
started immediately on launch and stopped by the appearance of a stop-signal
file (see --stop-file), run onset detection, correct for measured system
latency, and score the detected timing against the real piece's reference
through the scoring engine.

Pitch is NOT detected here (polyphonic pitch transcription from a generic
recording is a much harder problem than onset detection, and out of scope
for this check) -- both the reference and the detected performance are
given the same dummy pitch, so every note always "matches" on pitch and
scoring is isolated to pure timing/rhythm accuracy against the real piece's
actual rhythmic structure (note durations, tempo, any tempo changes).

Caveat: if the recording is a partial/abbreviated performance (very common
for e.g. Fur Elise, where many short clips only play the opening section)
compared against a *full* reference, expect a lot of "missed" notes near
the end -- that reflects a structural mismatch between recording and
reference, not a detection failure.
"""
from __future__ import annotations

import copy
import json
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


def record_until_stopfile(stop_file: Path, sr: int = SAMPLE_RATE, input_device=None,
                           max_duration_sec: float = 300.0) -> np.ndarray:
    frames: list[np.ndarray] = []

    def callback(indata, frame_count, time_info, status):
        if status:
            print(f"  (audio status: {status})", file=sys.stderr)
        frames.append(indata.copy())

    print("錄音開始 -- 現在播放音樂。音樂結束後，跟我說一聲就會停止。")
    stream = sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                             device=input_device, callback=callback)
    start = time.time()
    with stream:
        while not stop_file.exists() and (time.time() - start) < max_duration_sec:
            time.sleep(0.2)

    print("錄音結束")
    if not frames:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(frames, axis=0).flatten()


def build_timing_only_reference(reference: dict) -> dict:
    """Same rhythmic structure as the real reference, but every note's
    pitch is overridden to DUMMY_PITCH -- isolates scoring to pure timing.
    """
    ref_copy = copy.deepcopy(reference)
    for note in ref_copy["notes"]:
        note["pitch"] = DUMMY_PITCH
        note["name"] = "tap"
    return ref_copy


def run(reference_path: str, latency_ms: float, save_wav: str | None,
        stop_file: str, input_device=None):
    reference = json.load(open(reference_path, encoding="utf-8"))
    timing_reference = build_timing_only_reference(reference)

    stop_path = Path(stop_file)
    stop_path.unlink(missing_ok=True)  # clear any stale signal from a previous run
    recording = record_until_stopfile(stop_path, SAMPLE_RATE, input_device)
    stop_path.unlink(missing_ok=True)
    duration_sec = len(recording) / SAMPLE_RATE
    print(f"錄到 {duration_sec:.1f} 秒的音訊")

    if save_wav:
        sf.write(save_wav, recording, SAMPLE_RATE)
        print(f"錄音已存到 {save_wav}")

    if duration_sec < 1.0:
        print("錄音太短，中止")
        return None

    onsets = detect_onsets(recording, SAMPLE_RATE)
    print(f"偵測到 {len(onsets)} 個 onset")
    if len(onsets) < 3:
        print("偵測到的音符太少，沒辦法做有意義的評分")
        return None

    corrected_onsets = onsets - (latency_ms / 1000.0)
    corrected_onsets = corrected_onsets[corrected_onsets >= 0]

    performance = [
        {"pitch": DUMMY_PITCH, "onset_sec": float(t), "dur_sec": 0.1, "velocity": 80}
        for t in corrected_onsets
    ]

    result = score_performance(timing_reference, performance, ScoringConfig())

    print(f"\n參考樂曲: {reference.get('title')} ({len(reference['notes'])} 個音符, {reference.get('tempo_bpm')} bpm)")
    print(f"總分: {result.summary.score}")
    print(f"子分數: {result.summary.sub_scores}")
    print(f"global_tempo_ratio: {result.summary.global_tempo_ratio}")
    print(f"tempo_trend: {result.summary.tempo_trend}")
    print(f"計數: {result.summary.counts}")

    counts = result.summary.counts
    if counts["missed"] > len(reference["notes"]) * 0.3:
        print(
            "\n注意: missed 數量偏高，如果這份錄音只彈了整首曲子的一部分"
            "(比如只彈開頭的A段)，這是正常的結構性落差，不代表偵測失敗。"
        )

    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="錄一段真實演奏並對照參考樂曲評分")
    parser.add_argument("reference", help="reference.json 路徑")
    parser.add_argument("--latency-ms", type=float, default=132.4)
    parser.add_argument("--input-device", default=None)
    parser.add_argument("--save-wav", default=None)
    parser.add_argument("--stop-file", required=True, help="錄音停止訊號檔路徑(出現這個檔案就停止錄音)")
    args = parser.parse_args()

    run(args.reference, args.latency_ms, args.save_wav, args.stop_file, args.input_device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
