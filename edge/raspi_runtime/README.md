# Raspberry Pi Runtime

This package is the Raspberry Pi side of PianoPal's acquisition loop.

It is responsible for:

- BLE connection to the left/right micro:bit hand devices
- local IMU raw JSONL storage
- real-time IMU posture inference on the Pi
- local prediction JSONL storage
- local audio file capture
- immediate speaker feedback
- SQLite session/artifact/model-run registration

The current audio and speaker integrations are adapter-based. Use command
adapters on the Pi, and keep the default no-op adapters for local development.

## Data Ownership

Keep these on the Raspberry Pi first:

```text
data/raw/sessions/<session_id>/imu_left.jsonl
data/raw/sessions/<session_id>/imu_right.jsonl
data/artifacts/sessions/<session_id>/imu_predictions.jsonl
data/raw/sessions/<session_id>/audio.wav
data/db/pianopal.sqlite3
```

After the session, sync `audio.wav` to the computer for heavier
`backend.audio_to_performance` and `backend.scoring` analysis. The computer can
later sync `performance.json`, `result.json`, and `augmented_result.json` back
as artifacts.

## Local Simulation

Run from the repo root:

```bash
python -m edge.raspi_runtime \
  --mode simulate \
  --duration-sec 3 \
  --user-id u_local_001 \
  --piece-id piece_demo \
  --piece-title Demo
```

This writes simulated IMU streams and prediction records, then registers them
in SQLite.

## Audio-Only Test

Use this when you want to test the Raspberry Pi microphone without BLE or
micro:bit devices:

```bash
python -m edge.raspi_runtime \
  --mode audio-only \
  --duration-sec 5 \
  --audio-command "arecord -f cd -t wav {output}" \
  --user-id u_local_001 \
  --piece-id piece_audio_test \
  --piece-title "Audio Test"
```

Expected output path:

```text
data/raw/sessions/<session_id>/audio.wav
```

The SQLite session status becomes `audio_acquired`, and `artifacts` contains a
single `raw_audio` path.

## Raspberry Pi BLE Mode

From the repo root on the Raspberry Pi:

```bash
python -m edge.raspi_runtime \
  --mode ble \
  --ble-config edge/microbit_rpi_comm/raspberry/config.json \
  --duration-sec 30 \
  --user-id u_local_001 \
  --piece-id piece_motion_test \
  --piece-title "Motion Test"
```

This connects both configured micro:bits, sends `CONNECT` then
`START LEFT`/`START RIGHT`, records CSV UART packets for `--duration-sec`,
sends `STOP`, and writes JSONL files under:

```text
edge/data/raw/sessions/<session_id>/imu_left.jsonl
edge/data/raw/sessions/<session_id>/imu_right.jsonl
edge/data/artifacts/sessions/<session_id>/imu_predictions.jsonl
```

Add audio recording only when the microphone path is ready:

```bash
python -m edge.raspi_runtime \
  --mode ble \
  --ble-config edge/microbit_rpi_comm/raspberry/config.json \
  --duration-sec 30 \
  --audio-command "arecord -f cd -t wav {output}" \
  --speaker-command "espeak {message}" \
  --user-id u_local_001 \
  --piece-id piece_fur_elise \
  --piece-title "Fur Elise"
```

The BLE data packet format is:

```text
hand,seq,timestamp_ms,
tip_ax,tip_ay,tip_az,tip_gx,tip_gy,tip_gz,
back_ax,back_ay,back_az,back_gx,back_gy,back_gz,
wrist_ax,wrist_ay,wrist_az
```

`seq` is per hand device, not shared globally across both hands.

## Backend Interface

The runtime uses `backend.db` to create:

- `practice_sessions`: status starts as `acquiring`, then becomes `acquired`
- `artifacts`: raw audio, left/right IMU JSONL, IMU predictions JSONL
- `model_runs`: real-time IMU posture inference metadata

The posture model adapter lives in `posture.py`. Replace
`ThresholdPostureModel` with the trained model loader for deployment.
