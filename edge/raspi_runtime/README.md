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

## Raspberry Pi BLE Mode

Example:

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
