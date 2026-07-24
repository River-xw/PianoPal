# Edge

Device-side code: the Raspberry Pi 5's LED-guided practice server (what the frontend actually talks to today), plus a separate sensor-acquisition runtime used for collecting/training the hand-posture model.

- `practice_server.py`: **the orchestrator the frontend viewer actually drives.** Runs on the Pi, serves the built frontend + the practice-session API (`/api/session/start`, `/api/session/status`, `/api/history`, ...) from one process. Coordinates `ws2812_guide_song.py` (LED guidance + recording) and, when a BLE posture rig is configured, `posture_capture.py` (real-time IMU posture scoring), then hands the recording to `scripts/grade_audio_reference_constrained.py` and stores the result via `backend.db.sqlite`. See its own module docstring for the full API surface, and [frontend/viewer/README.md](../frontend/viewer/README.md) for the page/session-flow side.
- `ws2812_guide_song.py` + `led_keyboard.py`: lights up the WS2812 strip along the keyboard in time with the reference score ("follow mode"), with live speed/pause/restart control over HTTP; optionally records audio for the session's exact duration; supports `--no-leds` (演奏模式, timing+recording only) and `--loop-start-measure`/`--loop-end-measure` (分段循環練習, loops a measure range indefinitely).
- `posture_capture.py`: standalone subprocess that runs the BLE micro:bit + MPU6050 posture pipeline (`edge/raspi_runtime/posture.py`/`ble.py`, reused as a library) for one practice session's duration and reduces the stream of posture-classifier predictions to a single 0-100 hand-shape score. Degrades gracefully (writes a `null` score, doesn't error) when no BLE rig is configured -- see `edge/practice_server.py`'s `HAND_SHAPE_PLACEHOLDER_SCORE` fallback.
- `microbit_rpi_comm/`: micro:bit BLE sender firmware + the low-level Raspberry Pi BLE receiver.
- `raspi_runtime/`: a **separate, acquisition-only** Raspberry Pi runtime (not wired into `practice_server.py`) that connects BLE hand sensors, microphone recording, speaker feedback, local SQLite artifact registration, and real-time IMU posture inference -- this is how the posture-classifier training data (and the trained model under `models/gesture/`) gets collected in the first place. `posture_capture.py` above reuses its `posture.py`/`ble.py` modules directly rather than shelling out to this whole runtime.

## Two Raspberry Pi entry points -- which one do you want?

| Aspect | `practice_server.py` | `raspi_runtime` |
|---|---|---|
| Who talks to it | The frontend viewer (built React app), over HTTP | `scripts/train_imu_from_session.py` / posture-model training workflow |
| What it does | LED-guided practice session end-to-end: guide, record, grade, store history | Raw sensor + audio *acquisition* only, no scoring |
| When to run it | Every time someone practices | When collecting new posture-labeled training data |

## `practice_server.py` Data Flow

```text
POST /api/session/start (song, mode=learn|perform, brightness, loop range...)
  -> ws2812_guide_song.py subprocess (LED guide + arecord)
  -> posture_capture.py subprocess, if a BLE rig is configured (parallel, optional)
  -> scripts/grade_audio_reference_constrained.py (backend.audio_to_performance -> backend.scoring)
  -> data/session_scratch/results/<user>/<session_id>.json + backend.db.sqlite
  -> GET /api/history, /api/history/<id> for the frontend's "我的" page
```

Run it (on the Pi, after `rsync`-ing `backend/` + the built `frontend/viewer/dist/` over -- see frontend/viewer/README.md):

```bash
python3 edge/practice_server.py
```

## `raspi_runtime` Acquisition Data Flow

The Raspberry Pi owns real-time work:

```text
micro:bit BLE IMU packets
  -> local raw JSONL
  -> local sliding-window posture inference
  -> local prediction JSONL
  -> speaker feedback
  -> SQLite session/artifact/model-run records

microphone
  -> local audio.wav
```

The computer owns heavier after-session analysis:

```text
audio.wav from Raspberry Pi
  -> backend.audio_to_performance
  -> backend.scoring
  -> result.json / augmented_result.json
  -> frontend viewer / LLM feedback
```

Run a local smoke test without hardware:

```bash
python -m edge.raspi_runtime --mode simulate --duration-sec 3 \
  --user-id u_local_001 --piece-id piece_demo --piece-title Demo
```

Run on Raspberry Pi with BLE, microphone, and speaker command adapters:

```bash
python -m edge.raspi_runtime \
  --mode ble \
  --ble-config edge/microbit_rpi_comm/raspberry/config.json \
  --audio-command "arecord -f cd -t wav {output}" \
  --speaker-command "espeak {message}" \
  --user-id u_local_001 \
  --piece-id piece_fur_elise \
  --piece-title "Fur Elise"
```
