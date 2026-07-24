# Data

Local datasets, sample references, generated performances, and experiment artifacts.

Large or private datasets should stay out of git unless the team explicitly decides otherwise.

Notable subdirectories that exist today:

- `db/pianopal.sqlite3`: the `backend.db` SQLite index (users/pieces/practice_sessions/artifacts/model_runs) -- see [../backend/db/README.md](../backend/db/README.md).
- `bf3738c_keybank/`: recorded per-key audio samples + the trained keyboard timbre profile for the BF-3738C 37-key keyboard (see `scripts/train_keybank_from_scale.py`/`train_keyboard_profile.py`), used to calibrate/constrain audio transcription.
- `session_scratch/`: per-session scratch files written by `edge/practice_server.py`/`scripts/session_server.py` while a practice session runs (recordings, guide JSON) plus `results/<username>/<session_id>.json`, the permanent per-session result copies the "我的" history page reads back.
- `artifacts/`, `raw/`: acquisition-pipeline outputs from `edge/raspi_runtime` (IMU JSONL, posture predictions, audio) -- see [../edge/raspi_runtime/README.md](../edge/raspi_runtime/README.md).
