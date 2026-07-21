"""Command-line entry point for Raspberry Pi acquisition."""

from __future__ import annotations

from pathlib import Path
import argparse
import asyncio

from .audio import CommandAudioRecorder, NullAudioRecorder
from .session import RuntimeConfig, default_session_id, run_session
from .speaker import CommandSpeaker, ConsoleSpeaker


REPO_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run PianoPal Raspberry Pi acquisition",
    )
    parser.add_argument("--user-id", default="u_local_001")
    parser.add_argument("--user-name", default="Local User")
    parser.add_argument("--piece-id", default="piece_unknown")
    parser.add_argument("--piece-title", default="Unknown Piece")
    parser.add_argument("--piece-composer", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--target-bpm", type=int, default=None)
    parser.add_argument("--data-root", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--mode", choices=["simulate", "ble", "audio-only"], default="simulate")
    parser.add_argument("--duration-sec", type=float, default=5.0)
    parser.add_argument("--ble-config", type=Path, default=None)
    parser.add_argument(
        "--audio-command",
        default=None,
        help='External recorder command, e.g. "arecord -f cd -t wav {output}"',
    )
    parser.add_argument(
        "--speaker-command",
        default=None,
        help='External feedback command, e.g. "espeak {message}"',
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = RuntimeConfig(
        user_id=args.user_id,
        user_name=args.user_name,
        piece_id=args.piece_id,
        piece_title=args.piece_title,
        piece_composer=args.piece_composer,
        session_id=args.session_id or default_session_id(),
        data_root=args.data_root,
        mode=args.mode,
        ble_config=args.ble_config,
        duration_sec=args.duration_sec,
        target_bpm=args.target_bpm,
        db_path=args.db_path,
    )
    audio = CommandAudioRecorder(args.audio_command) if args.audio_command else NullAudioRecorder()
    speaker = CommandSpeaker(args.speaker_command) if args.speaker_command else ConsoleSpeaker()

    paths = asyncio.run(
        run_session(
            config,
            audio_recorder=audio,
            speaker=speaker,
        )
    )
    print(f"Session stored under {paths.raw_dir}")
