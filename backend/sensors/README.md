# Hand Sensor Data

This module defines the local shape for PianoPal's hand IMU data. It is meant
for the Raspberry Pi collection script and downstream posture-classification
pipeline.

## Hardware Shape

Each hand has one micro:bit on the wrist. It gathers:

- fingertip MPU6050: acceleration xyz + gyroscope xyz
- hand-back MPU6050: acceleration xyz + gyroscope xyz
- wrist micro:bit: acceleration xyz only

The storage schema normalizes all axes to `x`, `y`, `z`. If device firmware
reports axes in a different physical order, convert them before writing JSONL.

## Transport Packet

The simple single-IMU packet:

```text
R,timestamp,ax,ay,az,gx,gy,gz
```

is useful for early experiments, but the current hardware needs one aggregate
packet per hand:

```text
hand,seq,timestamp_ms,
tip_ax,tip_ay,tip_az,tip_gx,tip_gy,tip_gz,
back_ax,back_ay,back_az,back_gx,back_gy,back_gz,
wrist_ax,wrist_ay,wrist_az
```

Example:

```text
R,381,15230,120,-84,16320,3.2,-6.1,1.8,98,-70,16288,2.1,-4.4,1.2,110,-66,16310
```

Rules:

- one packet per line
- each line ends with `\n`
- field order is fixed
- no debug text on the data channel
- invalid packets can be skipped
- each packet carries a monotonically increasing sequence number
- each packet carries the micro:bit timestamp
- the Raspberry Pi adds its own receive timestamp

## Raw JSONL Record

The Raspberry Pi should write one normalized JSON object per line:

```json
{
  "schema_version": "hand_imu_raw_v3",
  "hand": "R",
  "sequence_number": 381,
  "device_timestamp_ms": 15230,
  "received_at_unix_ms": 1784563200123,
  "sensors": {
    "fingertip": {
      "accel": {"x": 120.0, "y": -84.0, "z": 16320.0},
      "gyro": {"x": 3.2, "y": -6.1, "z": 1.8}
    },
    "wrist": {
      "accel": {"x": 110.0, "y": -66.0, "z": 16310.0},
      "gyro": null
    },
    "hand_back": {
      "accel": {"x": 98.0, "y": -70.0, "z": 16288.0},
      "gyro": {"x": 2.1, "y": -4.4, "z": 1.2}
    }
  }
}
```

Recommended files:

```text
data/raw/sessions/sess_20260720_001/imu_left.jsonl
data/raw/sessions/sess_20260720_001/imu_right.jsonl
```

SQLite stores those paths in `artifacts`; ChromaDB stores derived feature
windows and posture labels.

## Keypress Windows

For rhythm/pitch alignment, keep the existing scoring idea:

```python
expected = [0.0, 0.5, 1.0, 1.5, 2.0]
played = [0.04, 0.43, 1.12, 1.68, 2.01]
```

The IMU training/inference window should be anchored to the actual
microphone-detected onset:

```text
window_start = played_onset_sec - 0.5
window_end = played_onset_sec + 0.3
```

For the sample data:

| ref_index | expected | played | offset_ms | window |
| --- | ---: | ---: | ---: | --- |
| 0 | 0.00 | 0.04 | 40 | 0.00-0.34 |
| 1 | 0.50 | 0.43 | -70 | 0.00-0.73 |
| 2 | 1.00 | 1.12 | 120 | 0.62-1.42 |
| 3 | 1.50 | 1.68 | 180 | 1.18-1.98 |
| 4 | 2.00 | 2.01 | 10 | 1.51-2.31 |

These windows later become posture-classification samples:

```json
{
  "schema_version": "imu_feature_window_v1",
  "session_id": "sess_20260720_001",
  "ref_index": 2,
  "hand": "R",
  "window_start_sec": 0.62,
  "window_end_sec": 1.42,
  "features": {
    "fingertip_accel_rms_x": 123.4,
    "hand_back_gyro_peak_z": 8.2,
    "wrist_accel_mean_y": -72.1
  },
  "predicted_label": "wrist_tension",
  "confidence": 0.91,
  "model_version": "imu_posture_v1"
}
```

## Audio-Triggered IMU Training

Use the backend audio pipeline as the source of truth for note onsets. The
audio step produces the existing `performance.json` shape:

```json
[
  {"pitch": 60, "onset_sec": 0.42, "dur_sec": 0.31, "velocity": 82}
]
```

Training then merges notes with near-identical onsets into one physical
keypress/chord event and cuts IMU windows around those audio onsets. The audio
does not decide the posture label; it only decides when to cut the window.
Each event produces one candidate sample per hand. Both hands use the same
feature names and label space, so the model does not learn left/right identity.
The `hand` field remains as metadata for data-quality debugging. Each sample
uses all sensors on that hand:

- fingertip MPU6050 accel/gyro
- hand-back MPU6050 accel/gyro
- wrist micro:bit accel

Recommended flow when `performance.json` already exists:

```bash
python3 scripts/train_imu_from_session.py \
  --session-id sess_20260722_001 \
  --session-dir data/raw/sessions/sess_20260722_001 \
  --performance-json data/artifacts/sessions/sess_20260722_001/performance.json \
  --labels data/artifacts/sessions/sess_20260722_001/imu_labels.json
```

New runtime sessions also contain:

```text
data/raw/sessions/<session_id>/timing.json
```

When `--session-dir` is provided, the training script loads this file
automatically. It aligns the micro:bit device clock to the audio recorder's
wall-clock start using the Raspberry Pi receive timestamps in the IMU JSONL.
Older sessions without `timing.json` use the legacy first-IMU-packet origin;
`--imu-time-offset-sec` remains available for manual correction.

Feature extraction retains both hand candidates for every audio event and marks
each row with `usable_for_training`. Before feature calculation, it removes any
packet whose fingertip, hand-back, or wrist aggregate reading is all zero. By
default, a hand sample must retain at least three packets and at least 80% of
the packets originally present in the window. A bad hand is dropped without
discarding the other hand from the same event. Rejected rows remain in
`imu_keypress_features.jsonl` with `quality_reasons`, while model training
ignores them automatically. Use `--min-valid-samples-per-hand` and
`--min-valid-ratio` to adjust these thresholds.

If BLE reconnects and the micro:bit sequence number/device timestamp resets,
the alignment code starts a new clock segment and estimates its wall-clock
offset independently. Windows inside the disconnected gap naturally fail the
sample-count quality check.

Or let the script call `backend.audio_to_performance` from `audio.wav`:

```bash
python3 scripts/train_imu_from_session.py \
  --session-id sess_20260722_001 \
  --session-dir data/raw/sessions/sess_20260722_001 \
  --labels data/artifacts/sessions/sess_20260722_001/imu_labels.json \
  --save-performance-json data/artifacts/sessions/sess_20260722_001/performance.json
```

The labels file can be a simple list with one label per audio-triggered event:

```json
["normal", "finger_collapse", "normal", "wrist_collapse"]
```

Outputs:

```text
data/artifacts/sessions/<session_id>/imu_keypress_features.jsonl
models/gesture/<session_id>_hand_imu_model.json
```
