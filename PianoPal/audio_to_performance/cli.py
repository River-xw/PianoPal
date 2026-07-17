"""CLI: python -m audio_to_performance input.wav -o performance.json
       [--denoise] [--bandpass] [--normalize] [--onset-thresh 0.5] [--save-midi out.mid]
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import AudioToPerformanceConfig
from .errors import AudioToPerformanceError
from .pipeline import transcribe


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m audio_to_performance",
        description="Transcribe a solo-piano recording into a performance.json for the scoring engine.",
    )
    parser.add_argument("input", help="Path to a .wav/.mp3/.m4a/.flac/.ogg recording.")
    parser.add_argument("-o", "--output", help="Path to write performance.json. Defaults to stdout.")
    parser.add_argument("--denoise", action="store_true", help="Enable spectral-gating noise reduction.")
    parser.add_argument("--bandpass", action="store_true", help="Enable piano-range band-pass filter.")
    parser.add_argument("--normalize", action="store_true", help="Enable peak loudness normalization.")
    parser.add_argument("--onset-thresh", type=float, default=0.5, help="basic-pitch onset_threshold.")
    parser.add_argument("--frame-thresh", type=float, default=0.3, help="basic-pitch frame_threshold.")
    parser.add_argument("--min-note-length-ms", type=float, default=58.0, help="basic-pitch minimum_note_length (ms).")
    parser.add_argument("--save-midi", default=None, help="Also save the intermediate transcribed MIDI here.")
    parser.add_argument(
        "--suppress-harmonics", action="store_true",
        help="Drop notes that look like harmonic/overtone bleed from a nearby louder note.",
    )
    parser.add_argument(
        "--suppress-split-notes", action="store_true",
        help="Merge a note that looks like a re-attack of the same held note's own decay.",
    )
    args = parser.parse_args(argv)

    config = AudioToPerformanceConfig(
        denoise=args.denoise, bandpass=args.bandpass, normalize=args.normalize,
        onset_threshold=args.onset_thresh, frame_threshold=args.frame_thresh,
        minimum_note_length_ms=args.min_note_length_ms,
        suppress_harmonics=args.suppress_harmonics,
        suppress_split_notes=args.suppress_split_notes,
    )

    try:
        performance = transcribe(wav_path=args.input, config=config, save_midi_path=args.save_midi)
    except AudioToPerformanceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_json = json.dumps(performance, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
    else:
        print(output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
