# Models

Trained model assets used by the hand-posture scoring pipeline (`edge/raspi_runtime/posture.py`, `edge/posture_capture.py`).

- `gesture/`: hand-posture classifiers trained from IMU sessions (see `backend/sensors/README.md` and `scripts/train_posture_from_sessions.py`).
  - `left_hand_posture_classifier.joblib` -- the current production model (scikit-learn `Pipeline`, loaded via `SklearnPostureModel`). This is what `edge/posture_capture.py` and `edge/raspi_runtime`'s `--posture-model` flag load by default.
  - `left_hand_posture_classifier.json` -- a portable export of the same model as a plain-JSON random-forest (`PortableRandomForestPostureModel`), so it can run on a Pi with no scikit-learn/joblib installed at all.
  - `sess_normal_01_hand_imu_model.json` -- an earlier single-session baseline model from `scripts/train_imu_from_session.py`, kept for reference/comparison.

No `pitch/`/`shared/` split has materialized -- audio/pitch transcription still lives entirely in `backend/audio_to_performance/` (basic-pitch + reference-constrained re-verification), not as a separate trained model under here. Add those subdirectories if/when that changes.
