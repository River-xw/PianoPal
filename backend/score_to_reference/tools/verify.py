"""Verification helper for spot-checking convert() accuracy on a real score.

Two independent checks, meant to be run against your own musicxml/midi files:

1. Recounts notes straight from the raw file (XML / MIDI bytes), bypassing
   musicxml_parser.py / midi_parser.py entirely -- a bug in our own parser
   won't show up in both counts at once.
2. Renders a piano-roll PNG (onset beat x pitch, colored by hand) so you can
   eyeball it side by side with the actual sheet music.
"""
from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from ..core import convert
from ..errors import ScoreReferenceError

_HAND_COLOR = {"R": "#2a78d6", "L": "#008300"}  # validated categorical slots 1 & 2
_SURFACE = "#fcfcfb"
_GRID = "#e1e0d9"
_AXIS = "#c3c2b7"
_TEXT_PRIMARY = "#0b0b0b"
_TEXT_MUTED = "#898781"


def _read_musicxml_root(path: str) -> ET.Element:
    if path.lower().endswith(".mxl"):
        with zipfile.ZipFile(path) as zf:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            rootfile = container.find(".//rootfile").attrib["full-path"]
            return ET.fromstring(zf.read(rootfile))
    return ET.parse(path).getroot()


def independent_note_count(path: str) -> Optional[int]:
    """Recount notes from the raw file, independent of our own parser."""
    ext = os.path.splitext(path)[1].lower()
    if ext in {".musicxml", ".xml", ".mxl"}:
        root = _read_musicxml_root(path)
        return sum(1 for note_el in root.iter("note") if note_el.find("pitch") is not None)
    if ext in {".mid", ".midi"}:
        import mido

        midi_file = mido.MidiFile(path)
        return sum(
            1
            for track in midi_file.tracks
            for msg in track
            if msg.type == "note_on" and msg.velocity > 0
        )
    return None


def plot_piano_roll(reference: dict, out_path: str) -> None:
    notes = reference["notes"]
    if not notes:
        raise ValueError("reference has no notes to plot")

    numerator, denominator = (int(x) for x in reference["time_signature"].split("/"))
    beats_per_measure = numerator * 4.0 / denominator
    duration_beats = reference["duration_beats"]

    fig, ax = plt.subplots(figsize=(max(8.0, duration_beats / 4.0), 6.0))
    fig.patch.set_facecolor(_SURFACE)
    ax.set_facecolor(_SURFACE)

    pitches = [n["pitch"] for n in notes]
    ax.set_ylim(min(pitches) - 2, max(pitches) + 2)
    ax.set_xlim(-0.5, duration_beats + 0.5)

    n_measures = int(duration_beats // beats_per_measure) + 1
    for m in range(n_measures + 1):
        ax.axvline(m * beats_per_measure, color=_GRID, linewidth=1, zorder=0)

    bar_height = 0.6
    for n in notes:
        color = _HAND_COLOR.get(n["hand"], _TEXT_MUTED)
        x, w = n["onset_beats"], max(n["dur_beats"], 0.05)
        patch = FancyBboxPatch(
            (x, n["pitch"] - bar_height / 2), w, bar_height,
            boxstyle="round,pad=0,rounding_size=0.08",
            linewidth=0.5, edgecolor=_SURFACE, facecolor=color, zorder=2,
        )
        ax.add_patch(patch)

    ax.set_xlabel("Beat (quarter notes from start)", color=_TEXT_MUTED)
    ax.set_ylabel("MIDI pitch", color=_TEXT_MUTED)
    ax.tick_params(colors=_TEXT_MUTED)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("bottom", "left"):
        ax.spines[side].set_color(_AXIS)

    title = reference.get("title") or "score"
    ax.set_title(
        f"{title} — {reference['tempo_bpm']} bpm, "
        f"{reference['time_signature']}, {reference['key']}",
        color=_TEXT_PRIMARY, fontsize=12,
    )

    legend_handles = [
        plt.Line2D([0], [0], marker="s", linestyle="", markersize=10,
                   markerfacecolor=color, markeredgecolor=color, label=hand)
        for hand, color in _HAND_COLOR.items()
    ]
    ax.legend(handles=legend_handles, loc="upper right", frameon=False, labelcolor=_TEXT_PRIMARY)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor=_SURFACE)
    plt.close(fig)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.score_to_reference.tools.verify",
        description="Cross-check convert() output against the raw file and render a piano-roll plot.",
    )
    parser.add_argument("input", help="Path to the score file (.musicxml/.xml/.mxl/.mid).")
    parser.add_argument("-o", "--out", default="piano_roll.png", help="Output PNG path.")
    args = parser.parse_args(argv)

    try:
        reference = convert(args.input)
    except ScoreReferenceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parsed_count = len(reference["notes"])
    raw_count = independent_note_count(args.input)

    hand_counts: dict = {}
    for n in reference["notes"]:
        hand_counts[n["hand"]] = hand_counts.get(n["hand"], 0) + 1

    print(f"title:          {reference['title']}")
    print(f"tempo_bpm:      {reference['tempo_bpm']}")
    print(f"time_signature: {reference['time_signature']}")
    print(f"key:            {reference['key']}")
    print(f"duration_beats: {reference['duration_beats']:.2f}")
    print(f"duration_sec:   {reference['duration_sec']:.2f}")
    print(f"notes (parsed by convert()): {parsed_count}")
    if raw_count is not None:
        status = "OK" if raw_count == parsed_count else "MISMATCH -- check for dropped/duplicated notes"
        print(f"notes (raw file recount):   {raw_count}  [{status}]")
    print(f"hand distribution: {hand_counts}")

    plot_piano_roll(reference, args.out)
    print(f"\npiano roll saved to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
