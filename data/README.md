# Data

Local datasets, sample references, generated performances, and experiment artifacts.

Large or private datasets should stay out of git unless the team explicitly decides otherwise.

Runtime data is intentionally split by purpose:

```text
data/formal_assessments/
  sessions/<username>/<session_id>/
    performance.wav
    motion_assessment.json
    audio_debug.json
    result.json

data/training_collection/
  raw/sessions/<session_id>/
    audio.wav
    imu_left.jsonl
    imu_right.jsonl
    timing.json
  artifacts/sessions/<session_id>/
    imu_predictions.jsonl
```

`edge/practice_server.py` owns formal assessment data. `python -m
edge.raspi_runtime` owns raw training collection. Do not train directly from
`formal_assessments`; formal sessions deliberately keep only the aggregate
motion assessment rather than the raw IMU stream.
