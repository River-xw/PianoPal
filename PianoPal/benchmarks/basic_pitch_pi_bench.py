"""Benchmarks basic-pitch transcription speed/memory on-device (the Pi
itself), to decide whether moving transcription from laptop/cloud to
on-device is realistic -- and if so, whether near-real-time feedback is
possible or only batch-after-the-fact.

Deliberately uses the LIGHTWEIGHT inference backend appropriate for ARM:
tflite-runtime first (the standalone package, not the full `tensorflow`
wheel -- see basic_pitch's own TFLITE_PRESENT/TF_PRESENT detection in its
__init__.py), falling back to ONNX Runtime, and printing a loud warning if
only the full TensorFlow SavedModel backend is available -- that's the
backend this benchmark exists specifically to avoid on Pi (heavy deps, slow
on ARM), so silently using it would make the benchmark answer the wrong
question.

Everything here runs in a single process with the model loaded ONCE and
reused across all timed calls: predict()'s `model_or_model_path` accepts an
already-constructed `Model` instance specifically so repeated calls skip
reloading -- otherwise "discard the first run as warmup" wouldn't actually
separate one-time load/JIT-warmup cost from steady-state inference cost.
"""
from __future__ import annotations

import platform
import resource
import statistics
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

SR = 44100  # a realistic recording rate; predict() resamples internally as needed


# --- system info --------------------------------------------------------------


def is_64bit_os() -> bool:
    """Checks the kernel-reported architecture (not just the Python build),
    since a 32-bit Python could in principle run on a 64-bit kernel and vice
    versa -- what matters here is what the OS itself is.
    """
    machine = platform.machine().lower()
    return machine in {"aarch64", "arm64", "x86_64", "amd64"}


def get_pi_model() -> str:
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            with open(path, "rb") as fh:
                return fh.read().rstrip(b"\x00").decode("utf-8", errors="replace")
        except OSError:
            continue
    return "unknown (not a Raspberry Pi, or device-tree model file not found)"


def get_ram_info() -> dict:
    try:
        import psutil

        total = psutil.virtual_memory().total
        return {"total_mb": round(total / (1024 * 1024), 1), "source": "psutil"}
    except ImportError:
        pass
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return {"total_mb": round(kb / 1024, 1), "source": "/proc/meminfo"}
    except OSError:
        pass
    return {"total_mb": None, "source": "unavailable"}


def get_system_info() -> dict:
    return {
        "pi_model": get_pi_model(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "is_64bit_os": is_64bit_os(),
        "python_version": platform.python_version(),
        "ram": get_ram_info(),
    }


# --- backend selection ---------------------------------------------------------


@dataclass
class BackendChoice:
    name: str
    model_path: Path
    is_lightweight: bool
    warning: Optional[str] = None


def select_backend():
    import basic_pitch

    if basic_pitch.TFLITE_PRESENT:
        path = basic_pitch.build_icassp_2022_model_path(basic_pitch.FilenameSuffix.tflite)
        return BackendChoice("tflite", path, is_lightweight=True)
    if basic_pitch.ONNX_PRESENT:
        path = basic_pitch.build_icassp_2022_model_path(basic_pitch.FilenameSuffix.onnx)
        return BackendChoice(
            "onnx", path, is_lightweight=True,
            warning="tflite-runtime not available -- falling back to ONNX Runtime (still lightweight, not the full TF backend).",
        )
    if basic_pitch.TF_PRESENT:
        path = basic_pitch.build_icassp_2022_model_path(basic_pitch.FilenameSuffix.tf)
        return BackendChoice(
            "tensorflow (full SavedModel)", path, is_lightweight=False,
            warning=(
                "WARNING: only the full TensorFlow SavedModel backend is available "
                "(neither tflite-runtime nor onnxruntime is installed). This is exactly "
                "the heavy backend this benchmark exists to avoid on Pi -- install "
                "tflite-runtime (or onnxruntime) and re-run before trusting these numbers "
                "as representative of the lightweight on-device path."
            ),
        )
    raise RuntimeError(
        "No usable basic-pitch inference backend found. Install one of: "
        "tflite-runtime, onnxruntime, or tensorflow."
    )


# --- synthetic audio ------------------------------------------------------------


def _midi_to_freq(pitch: int) -> float:
    return 440.0 * 2 ** ((pitch - 69) / 12)


def _synth_note(freq_hz: float, duration_sec: float, sr: int) -> np.ndarray:
    n = int(duration_sec * sr)
    t = np.arange(n) / sr
    wave = (
        1.00 * np.sin(2 * np.pi * freq_hz * t)
        + 0.50 * np.sin(2 * np.pi * 2 * freq_hz * t)
        + 0.25 * np.sin(2 * np.pi * 3 * freq_hz * t)
    )
    envelope = np.exp(-2.0 * t)
    attack_n = max(1, int(0.005 * sr))
    envelope[:attack_n] *= np.linspace(0, 1, attack_n)
    return (wave * envelope * 0.3).astype(np.float32)


def synth_wav(duration_sec: float, sr: int = SR) -> np.ndarray:
    """A repeating scale of additive-harmonic sine notes filling the target
    duration -- speed benchmarking doesn't need real piano audio, just
    audio with note-like transient structure of the right length.
    """
    scale = [60, 62, 64, 65, 67, 69, 71, 72]  # C major scale, one octave
    note_dur = 0.5
    track = np.zeros(int(duration_sec * sr), dtype=np.float32)
    t = 0.0
    i = 0
    while t < duration_sec:
        pitch = scale[i % len(scale)]
        note_wave = _synth_note(_midi_to_freq(pitch), note_dur + 0.2, sr)
        start = int(t * sr)
        end = min(len(track), start + len(note_wave))
        if start >= len(track):
            break
        track[start:end] += note_wave[: end - start]
        t += note_dur
        i += 1
    peak = np.max(np.abs(track))
    if peak > 0:
        track = track / peak * 0.9
    return track


# --- memory ----------------------------------------------------------------------


def peak_rss_mb() -> float:
    """Process peak RSS since start (monotonic, not per-call) -- ru_maxrss is
    KB on Linux, bytes on macOS.
    """
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024.0 if platform.system() == "Linux" else 1024.0 * 1024.0
    return round(raw / divisor, 1)


# --- benchmark core ----------------------------------------------------------------


@dataclass
class DurationResult:
    duration_sec: float
    run_times_sec: list = field(default_factory=list)  # excludes the discarded warmup run
    mean_time_sec: float = 0.0
    stdev_time_sec: float = 0.0
    real_time_factor: float = 0.0
    peak_rss_mb: float = 0.0
    verdict: str = ""


VERDICT_THRESHOLDS = [
    (1.0, "faster than real-time -- near-live feedback feasible"),
    (3.0, "usable for short-delay feedback (a few seconds after playing a phrase)"),
    (float("inf"), "batch-only -- only practical to transcribe after a full practice session ends"),
]


def classify_real_time_factor(rtf: float) -> str:
    for threshold, verdict in VERDICT_THRESHOLDS:
        if rtf < threshold:
            return verdict
    return VERDICT_THRESHOLDS[-1][1]


def run_benchmark(durations: list, runs: int, model) -> list:
    import time

    from basic_pitch.inference import predict

    results = []
    for duration in durations:
        audio = synth_wav(duration)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        sf.write(wav_path, audio, SR)

        try:
            elapsed = []
            for _ in range(runs):
                start = time.perf_counter()
                predict(wav_path, model_or_model_path=model)
                elapsed.append(time.perf_counter() - start)
        finally:
            Path(wav_path).unlink(missing_ok=True)

        # discard the first run (cold-start/lazy-init warmup), per spec
        measured = elapsed[1:] if len(elapsed) > 1 else elapsed
        mean_time = statistics.mean(measured)
        stdev_time = statistics.stdev(measured) if len(measured) > 1 else 0.0
        rtf = mean_time / duration

        result = DurationResult(
            duration_sec=duration,
            run_times_sec=[round(t, 4) for t in measured],
            mean_time_sec=round(mean_time, 4),
            stdev_time_sec=round(stdev_time, 4),
            real_time_factor=round(rtf, 4),
            peak_rss_mb=peak_rss_mb(),
            verdict=classify_real_time_factor(rtf),
        )
        results.append(result)
        print(
            f"  {duration:>5.0f}s audio: mean={result.mean_time_sec:.3f}s "
            f"(+/-{result.stdev_time_sec:.3f}) RTF={result.real_time_factor:.2f} "
            f"peak_rss={result.peak_rss_mb:.0f}MB  -> {result.verdict}"
        )

    return results


# --- CLI ---------------------------------------------------------------------------


def main(argv=None) -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.basic_pitch_pi_bench",
        description="Benchmark basic-pitch transcription speed/memory on this device.",
    )
    parser.add_argument("--durations", type=float, nargs="+", default=[5, 10, 20, 30], help="Audio durations (seconds) to benchmark.")
    parser.add_argument("--runs", type=int, default=3, help="Runs per duration (first is discarded as warmup).")
    parser.add_argument("-o", "--output", default=None, help="Path to write the JSON report.")
    args = parser.parse_args(argv)

    system_info = get_system_info()
    print("=== system info ===")
    for key, value in system_info.items():
        print(f"  {key}: {value}")

    if not system_info["is_64bit_os"]:
        print(
            "\nERROR: this looks like a 32-bit OS (platform.machine() == "
            f"'{system_info['machine']}'). TensorFlow/ONNX Runtime ARM wheels are "
            "often unavailable or broken on 32-bit Raspberry Pi OS -- reflash with "
            "the 64-bit image rather than debugging dependency errors from here.",
            file=sys.stderr,
        )
        return 1

    try:
        backend = select_backend()
    except RuntimeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    print(f"\n=== backend: {backend.name} ({backend.model_path}) ===")
    if backend.warning:
        print(backend.warning)

    from basic_pitch.inference import Model

    model = Model(backend.model_path)

    print(f"\n=== benchmark (durations={args.durations}, runs={args.runs}) ===")
    duration_results = run_benchmark(args.durations, args.runs, model)

    print("\n=== verdict table ===")
    header = f"{'duration_sec':>12} {'mean_sec':>10} {'stdev_sec':>10} {'RTF':>6} {'peak_rss_mb':>12}  verdict"
    print(header)
    for r in duration_results:
        print(f"{r.duration_sec:>12.0f} {r.mean_time_sec:>10.3f} {r.stdev_time_sec:>10.3f} {r.real_time_factor:>6.2f} {r.peak_rss_mb:>12.0f}  {r.verdict}")

    report = {
        "system_info": system_info,
        "backend": {"name": backend.name, "model_path": str(backend.model_path), "is_lightweight": backend.is_lightweight, "warning": backend.warning},
        "results": [
            {
                "duration_sec": r.duration_sec, "run_times_sec": r.run_times_sec,
                "mean_time_sec": r.mean_time_sec, "stdev_time_sec": r.stdev_time_sec,
                "real_time_factor": r.real_time_factor, "peak_rss_mb": r.peak_rss_mb,
                "verdict": r.verdict,
            }
            for r in duration_results
        ],
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nFull report written to {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
