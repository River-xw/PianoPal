#!/usr/bin/env python3
"""Piano practice guidance: play a song's timeline on the LED strip so the
player can follow which key to press next, in time.

"Follow" mode -- the song advances on its own clock at the reference tempo (or
slower/faster, adjustable live). At each note's onset the corresponding key's
LEDs light up; they turn off just before the note ends so a repeated note on
the same key visibly re-triggers. Left/right hand get different colors.

Two ways to control playback live, both backed by the same shared state so
either (or both) can be used in the same run:

  - Local keyboard (only when stdin is a real TTY, e.g. `ssh -t`):
        +/=   faster       -/_   slower
        space pause/resume  r    restart from the top
        q     quit
  - HTTP, when run with --http-port PORT (e.g. for the frontend's speed
    control -- see frontend/viewer/src/components/GuideControl.jsx):
        GET  /status                    -> {"speed":1.0,"paused":false,"song_pos":3.2,"song_end":28.8,"title":"..."}
        POST /control  {"action":"speed_set","value":1.2}
        POST /control  {"action":"speed_delta","value":0.1}
        POST /control  {"action":"pause_toggle"}
        POST /control  {"action":"restart"}
        POST /control  {"action":"quit"}

This runs on the Raspberry Pi and needs no backend deps: it reads a song JSON
whose top-level "notes" list is the score_to_reference format (each note has
pitch / onset_sec / dur_sec / hand). Produce one on the dev machine with:

    python3 -c "import json; from backend.score_to_reference.core import convert; \\
        json.dump(convert('docs/piano_music/twinkle_twinkle.mid'), open('twinkle.json','w'))"

then copy it next to edge/led_key_mapping.json on the Pi.

Optionally records audio (arecord on the Pi's own mic) for exactly the
guided session's duration, so the recording lines up with the LED timeline
-- see --record-output/--record-device.

Run:
    python3 edge/ws2812_guide_song.py twinkle.json
    python3 edge/ws2812_guide_song.py twinkle.json --http-port 8765   # + frontend control
    python3 edge/ws2812_guide_song.py twinkle.json --record-output take.wav   # + record along
    python3 edge/ws2812_guide_song.py twinkle.json --no-leds --record-output take.wav   # 演奏模式: no lights, timing+recording only
    python3 edge/ws2812_guide_song.py twinkle.json --loop-start-measure 5 --loop-end-measure 8   # 分段循環練習: repeat measures 5-8 forever until stopped
    ssh -t pi@... 'cd ~/PianoPal/edge && python3 ws2812_guide_song.py alabama.json'   # interactive
"""
from __future__ import annotations

import argparse
import bisect
import json
import select
import subprocess
import sys
import termios
import threading
import time
import tty
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rpi5_ws2812.ws2812 import Color

from led_keyboard import load_mapping, make_strip, pitch_to_leds

# per-hand colors (R = right, L = left); notes with no hand default to right
HAND_COLORS = {"R": Color(0, 255, 60), "L": Color(255, 40, 160)}
DEFAULT_COLOR = HAND_COLORS["R"]

# a note's light turns off this long before the next note starts, so a
# repeated same-key note blinks off-then-on instead of looking like one hold
OFF_GAP_SEC = 0.06
SPEED_STEP = 0.1
MIN_SPEED = 0.1
MAX_SPEED = 3.0
OFF = Color(0, 0, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guide a song on the LED strip in follow mode.")
    parser.add_argument("song", help="Song JSON in score_to_reference format (has a 'notes' list).")
    parser.add_argument("--brightness", type=float, default=0.25, help="0.0-1.0.")
    parser.add_argument("--speed", type=float, default=1.0, help="Initial playback speed (0.6 = slower/easier).")
    parser.add_argument("--lead-in-sec", type=float, default=3.0, help="Countdown before the first note.")
    parser.add_argument("--full-range", action="store_true",
                        help="Light each key's full 2-3 LED range instead of just its first LED (single-LED is now the default).")
    parser.add_argument("--http-port", type=int, default=None,
                        help="Serve GET /status and POST /control on this port for remote (e.g. frontend) control.")
    parser.add_argument("--record-output", default=None,
                        help="If given, record audio from --record-device to this WAV path for exactly the "
                             "guided session's duration (starts when the lead-in ends, stops when the song ends "
                             "or playback is quit/restarted) -- so the recording lines up with the LED timeline.")
    parser.add_argument("--record-device", default="plughw:2,0",
                        help="ALSA capture device for `arecord -D` (see `arecord -l` on the Pi for options).")
    parser.add_argument(
        "--no-leds", action="store_true",
        help="Skip all LED lighting (for 演奏模式/performance mode, which has no visual guidance) -- "
             "timing, recording, and HTTP status all still work unchanged, just no hardware/SPI access at all.",
    )
    parser.add_argument("--loop-start-measure", type=int, default=None,
                        help="分段循環練習: repeat measures [start, end] indefinitely instead of playing "
                             "straight through. Must be given together with --loop-end-measure.")
    parser.add_argument("--loop-end-measure", type=int, default=None,
                        help="See --loop-start-measure.")
    return parser.parse_args()


class _NullStrip:
    """Same interface as the real SPI-driven strip (num_pixels/
    set_pixel_color/show/clear), all no-ops -- used for --no-leds so _run()
    and the lead-in countdown work completely unmodified, and so no-LED runs
    never touch SPI/hardware at all (e.g. still works if the strip itself
    has an issue, or there's no keyboard LED mapping file on this machine)."""

    def num_pixels(self) -> int:
        return 0

    def set_pixel_color(self, *_args, **_kwargs) -> None:
        pass

    def show(self) -> None:
        pass

    def clear(self) -> None:
        pass


class AudioRecorder:
    """Thin arecord wrapper -- records for as long as start()..stop() spans.
    Self-contained (no import from edge/raspi_runtime) so this script keeps
    its "no backend deps" property; the command matches that module's
    CommandAudioRecorder pattern."""

    def __init__(self, device: str, output_path: str):
        self.device = device
        self.output_path = output_path
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(
            ["arecord", "-D", self.device, "-f", "cd", "-t", "wav", self.output_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None


def _build_timeline(notes: list, pitch_leds: dict[int, list[int]]):
    """Flatten notes into sorted (song_time_sec, kind, led, color) events;
    kind 0 = on (sorts first), 1 = off. song_time is in the score's own
    seconds -- the playback loop maps it to wall-clock at the current speed,
    so speed can change live. Skips pitches with no LED mapping (black keys)."""
    events = []
    for note in notes:
        pitch = int(note["pitch"])
        leds = pitch_leds.get(pitch)
        if not leds:
            continue
        color = HAND_COLORS.get(note.get("hand"), DEFAULT_COLOR)
        onset = float(note["onset_sec"])
        dur = float(note.get("dur_sec", 0.3) or 0.3)
        off_at = onset + max(0.08, dur - OFF_GAP_SEC)
        for led in leds:
            events.append((onset, 0, led, color))
            events.append((off_at, 1, led, None))
    events.sort(key=lambda e: (e[0], e[1]))
    return events


class PlaybackState:
    """Shared, lock-protected transport state -- mutated by the local
    keyboard reader and/or the HTTP control server, read by the playback
    loop. This is the single source of truth so both control paths can be
    used interchangeably (or at the same time) without stepping on each
    other."""

    def __init__(
        self, speed: float, title: str, song_end: float,
        loop_start: float | None = None, loop_end: float | None = None,
    ):
        self._lock = threading.Lock()
        self.speed = speed
        self.paused = False
        self.restart_requested = False
        self.quit_requested = False
        self.song_pos = 0.0
        self.recording = False
        self.title = title
        self.song_end = song_end
        # 分段循環練習: when both are set, tick() wraps song_pos back to
        # loop_start once it reaches loop_end, instead of ever finishing.
        self.loop_start = loop_start
        self.loop_end = loop_end

    def apply(self, action: str, value=None) -> None:
        with self._lock:
            if action == "speed_set" and value is not None:
                self.speed = min(MAX_SPEED, max(MIN_SPEED, round(float(value), 2)))
            elif action == "speed_delta" and value is not None:
                self.speed = min(MAX_SPEED, max(MIN_SPEED, round(self.speed + float(value), 2)))
            elif action == "pause_toggle":
                self.paused = not self.paused
            elif action == "restart":
                self.restart_requested = True
            elif action == "quit":
                self.quit_requested = True

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "title": self.title,
                "speed": self.speed,
                "paused": self.paused,
                "song_pos": round(self.song_pos, 2),
                "song_end": round(self.song_end, 2),
                "recording": self.recording,
            }

    def set_recording(self, recording: bool) -> None:
        with self._lock:
            self.recording = bool(recording)

    def tick(self, dt: float) -> tuple[float, bool, bool]:
        """Advance song_pos by dt*speed (unless paused), and atomically
        consume any pending restart request. Returns (song_pos, restarted,
        looped) -- looped is True when a loop is configured and song_pos just
        wrapped back to loop_start (analogous to restarted, but automatic)."""
        with self._lock:
            restarted = self.restart_requested
            self.restart_requested = False
            looped = False
            if restarted:
                self.song_pos = 0.0
            elif not self.paused:
                self.song_pos += dt * self.speed
                if self.loop_end is not None and self.song_pos >= self.loop_end:
                    self.song_pos = self.loop_start
                    looped = True
            return self.song_pos, restarted, looped


def _make_http_handler(state: PlaybackState):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, obj: dict, status: int = 200) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # CORS preflight
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path == "/status":
                self._send_json(state.snapshot())
            else:
                self._send_json({"error": "not found"}, status=404)

        def do_POST(self) -> None:
            if self.path != "/control":
                self._send_json({"error": "not found"}, status=404)
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send_json({"error": "invalid json"}, status=400)
                return
            action = payload.get("action")
            if action not in {"speed_set", "speed_delta", "pause_toggle", "restart", "quit"}:
                self._send_json({"error": f"unknown action {action!r}"}, status=400)
                return
            state.apply(action, payload.get("value"))
            self._send_json(state.snapshot())

        def log_message(self, fmt, *args) -> None:  # quiet -- don't spam stdout per request
            pass

    return Handler


@contextmanager
def _raw_keyboard():
    """Put the terminal in cbreak mode for single-key reads, if stdin is a
    TTY. Yields a read_key() that returns one pending char or None. When
    stdin isn't a TTY (automated run / HTTP-only control), or the fd is
    unusable at all (e.g. backgrounded over SSH without `< /dev/null`, whose
    stdin can be left in a hung-up state once the launching session closes),
    yields a no-op reader instead of raising."""
    try:
        is_tty = sys.stdin.isatty()
    except OSError:
        is_tty = False
    if not is_tty:
        yield lambda: None
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)

        def read_key():
            if select.select([sys.stdin], [], [], 0)[0]:
                return sys.stdin.read(1)
            return None

        yield read_key
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _apply_key(state: PlaybackState, key: str) -> None:
    if key in "+=":
        state.apply("speed_delta", SPEED_STEP)
    elif key in "-_":
        state.apply("speed_delta", -SPEED_STEP)
    elif key == " ":
        state.apply("pause_toggle")
    elif key == "r":
        state.apply("restart")
    elif key in ("q", "\x03"):
        state.apply("quit")


def _run(strip, events, state: PlaybackState, interactive_hint: bool) -> None:
    """Sampled playback: advance a song-time cursor by dt*speed each tick,
    firing events as it passes them, so speed changes (from either control
    path) take effect live."""
    with _raw_keyboard() as read_key:
        if interactive_hint:
            print("  controls: +/- speed  space pause  r restart  q quit")
        looping = state.loop_end is not None
        loop_start_index = (
            bisect.bisect_left([e[0] for e in events], state.loop_start) if looping else None
        )
        i = 0
        last = time.monotonic()
        while i < len(events) or looping:
            if state.quit_requested:
                print("  quit")
                break

            now = time.monotonic()
            dt = now - last
            last = now
            song_pos, restarted, looped = state.tick(dt)

            if restarted:
                for led in range(strip.num_pixels()):
                    strip.set_pixel_color(led, OFF)
                strip.show()
                i = 0
                song_pos = 0.0
                print("  restart")
                last = time.monotonic()
                continue

            if looped:
                for led in range(strip.num_pixels()):
                    strip.set_pixel_color(led, OFF)
                strip.show()
                i = loop_start_index
                song_pos = state.loop_start
                last = time.monotonic()
                continue

            dirty = False
            while i < len(events) and events[i][0] <= song_pos:
                _, kind, led, color = events[i]
                strip.set_pixel_color(led, color if kind == 0 else OFF)
                dirty = True
                i += 1
            if dirty:
                strip.show()

            key = read_key()
            if key:
                _apply_key(state, key)
                print(f"  speed {state.speed:.1f}x" if key in "+=-_" else "")

            time.sleep(0.004)


def main() -> int:
    args = parse_args()
    song = json.loads(Path(args.song).read_text(encoding="utf-8"))
    notes = song.get("notes", [])
    title = song.get("title", args.song)

    if args.no_leds:
        strip = _NullStrip()
        # Timing/recording still need a valid timeline -- map every pitch to
        # a placeholder LED index (never actually shown, since _NullStrip's
        # set_pixel_color is a no-op) so no note gets silently dropped the
        # way a real keyboard's LED mapping would drop black keys/notes
        # outside its range. Without this, _build_timeline would filter out
        # every note (no real mapping was loaded), leaving an empty
        # timeline -- song_end would be 0 and the session would end instantly.
        pitch_leds = {int(n["pitch"]): [0] for n in notes}
    else:
        mapping = load_mapping()
        pitch_leds = pitch_to_leds(mapping)
        if not args.full_range:
            pitch_leds = {pitch: leds[:1] for pitch, leds in pitch_leds.items()}
        strip = make_strip(mapping, brightness=args.brightness)

    events = _build_timeline(notes, pitch_leds)
    playable = sum(1 for n in notes if int(n["pitch"]) in pitch_leds)
    hands = sorted({n.get("hand") for n in notes if int(n["pitch"]) in pitch_leds})
    song_end = events[-1][0] if events else 0.0
    print(f"guiding: {title}  ({playable}/{len(notes)} notes on the keyboard, "
          f"start speed {args.speed}x, hands {hands})")

    loop_start_sec = loop_end_sec = None
    if args.loop_start_measure is not None and args.loop_end_measure is not None:
        loop_notes = [
            n for n in notes
            if args.loop_start_measure <= int(n.get("measure", 0)) <= args.loop_end_measure
        ]
        if not loop_notes:
            raise SystemExit(
                f"no notes found in measures {args.loop_start_measure}-{args.loop_end_measure}"
            )
        loop_start_sec = min(float(n["onset_sec"]) for n in loop_notes)
        loop_end_sec = max(float(n["onset_sec"]) + float(n.get("dur_sec", 0.2) or 0.2) for n in loop_notes)
        print(f"  looping measures {args.loop_start_measure}-{args.loop_end_measure} "
              f"({loop_start_sec:.1f}s-{loop_end_sec:.1f}s) until stopped")

    state = PlaybackState(
        speed=args.speed, title=title, song_end=song_end,
        loop_start=loop_start_sec, loop_end=loop_end_sec,
    )

    http_server = None
    if args.http_port is not None:
        http_server = ThreadingHTTPServer(("0.0.0.0", args.http_port), _make_http_handler(state))
        threading.Thread(target=http_server.serve_forever, daemon=True).start()
        print(f"  http control on :{args.http_port}  (GET /status, POST /control)")

    for remaining in range(int(args.lead_in_sec), 0, -1):
        print(f"  starting in {remaining}...")
        for i in range(strip.num_pixels()):
            strip.set_pixel_color(i, Color(20, 20, 20))
        strip.show()
        time.sleep(0.15)
        strip.clear()
        time.sleep(0.85)

    recorder = None
    if args.record_output:
        recorder = AudioRecorder(args.record_device, args.record_output)
        recorder.start()
        state.set_recording(True)
        print(f"  recording to {args.record_output} (device {args.record_device})")

    try:
        _run(strip, events, state, interactive_hint=sys.stdin.isatty())
    except KeyboardInterrupt:
        pass
    finally:
        strip.clear()
        if recorder is not None:
            recorder.stop()
            state.set_recording(False)
            print(f"  recording stopped: {args.record_output}")
        if http_server is not None:
            http_server.shutdown()
        print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
