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
data/raw/sessions/<session_id>/timing.json
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

The SQLite session status becomes `audio_acquired`, and `artifacts` contains
the raw audio and acquisition timing paths.

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

This connects both configured micro:bits and waits up to 45 seconds for an
initial packet from each hand before playing the start prompt and starting
audio recording. If a hand is still missing, acquisition continues while BLE
keeps retrying; `timing.json` records it in `imu.initial_missing_hands`.
The `--duration-sec` clock therefore covers overlapping audio and IMU
acquisition. It sends `STOP` at the end and writes files under:

```text
data/raw/sessions/<session_id>/imu_left.jsonl
data/raw/sessions/<session_id>/imu_right.jsonl
data/raw/sessions/<session_id>/timing.json
data/artifacts/sessions/<session_id>/imu_predictions.jsonl
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

Use the trained posture classifier on the Raspberry Pi by copying the model
and passing `--posture-model`. If the right-hand data is known to be bad, keep
raw collection for both hands but run posture detection only on the left hand:

```bash
python -m edge.raspi_runtime \
  --mode ble \
  --ble-config edge/microbit_rpi_comm/raspberry/config.json \
  --duration-sec 30 \
  --posture-model models/gesture/left_hand_posture_classifier.joblib \
  --posture-hands L \
  --user-id u_local_001 \
  --piece-id piece_posture_test \
  --piece-title "Posture Test"
```

Predictions are written to:

```text
data/artifacts/sessions/<session_id>/imu_predictions.jsonl
```

The BLE data packet format is:

```text
hand,seq,timestamp_ms,
tip_ax,tip_ay,tip_az,tip_gx,tip_gy,tip_gz,
back_ax,back_ay,back_az,back_gx,back_gy,back_gz,
wrist_ax,wrist_ay,wrist_az
```

`seq` is per hand device, not shared globally across both hands.

An individual `SENSOR_ERROR` warning does not stop the session. The failed
sensor's fields are stored as zero while the remaining sensors continue. A BLE
disconnect is retried every two seconds. Missing or zero-filled windows are
excluded later by the training quality filter.

`timing.json` records the estimated audio recorder start time on the Raspberry
Pi clock. During feature extraction, each hand's device timestamps are mapped
to that clock using the median of
`received_at_unix_ms - device_timestamp_ms`. This smooths BLE receive jitter
while preserving the real delay between audio and IMU startup.

## Backend Interface

The runtime uses `backend.db` to create:

- `practice_sessions`: status starts as `acquiring`, then becomes `acquired`
- `artifacts`: raw audio, acquisition timing, left/right IMU JSONL, IMU predictions JSONL
- `model_runs`: real-time IMU posture inference metadata

The posture model adapter lives in `posture.py`. `load_posture_model(path)`
picks the right loader from the file extension -- `.joblib` -> `SklearnPostureModel`,
`.json` -> `PortableRandomForestPostureModel` (no scikit-learn needed to run
it, just this repo's own tree-walking code) -- and falls back to the
threshold-rule `ThresholdPostureModel` placeholder only when `path` is
`None`. A trained model already exists at
`models/gesture/left_hand_posture_classifier.joblib` (see the `--posture-model`
example above) -- `edge/posture_capture.py` (the practice-session-facing
posture scorer, see [../README.md](../README.md)) loads this same model by
default too, so this acquisition runtime and the main practice flow share one
trained classifier.
