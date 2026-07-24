# Data

Local datasets, sample references, generated performances, and experiment artifacts.

Large or private datasets should stay out of git unless the team explicitly decides otherwise.

- `db/pianopal.sqlite3`: the `backend.db` SQLite index (users/pieces/practice_sessions/artifacts/model_runs) -- see [../backend/db/README.md](../backend/db/README.md).
- `bf3738c_keybank/`: recorded per-key audio samples + the trained keyboard timbre profile for the BF-3738C 37-key keyboard (see `scripts/train_keybank_from_scale.py`/`train_keyboard_profile.py`), used to calibrate/constrain audio transcription. Only the 22 white keys are sampled/profiled today -- see [../backend/audio_to_performance/README.md](../backend/audio_to_performance/README.md) for how a song's black-key/out-of-range notes are handled (skipped from LED guidance and excluded from scoring, not counted as missed).

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
