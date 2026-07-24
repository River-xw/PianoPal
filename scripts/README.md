# Scripts

Developer-facing wrappers around the main pipeline.

## Grading

- `grade_audio_reference_constrained.py`: **the current production grading script** -- what `edge/practice_server.py`/`scripts/session_server.py` shell out to after a practice session. Transcribes a recording constrained to a known keyboard profile, aligns it against a reference score via `backend.scoring` (`--mode reference-dtw`, the default; `--mode reference-grid` is the older linear-time-alignment mode, kept for comparison, no longer the default), and writes a result.json. Full detail (mode comparison, `--score-weight-*`/`--hand-shape-score` flags, `--emit-wrong-pitch`, keyboard-profile calibration) is in [backend/audio_to_performance/README.md](../backend/audio_to_performance/README.md).
- `grade_audio.py`: the older, pre-reference-constrained grading script (`basic-pitch` transcription with no keyboard-profile constraint). Still present for comparison; not the production path.
- `grade_against_demo_audio.py`: grades a student recording against a **demo recording** instead of a MIDI/MusicXML reference (no score file needed) -- see `backend.audio_to_performance.audio_reference.grade_student_against_demo`.
- `grade.py`: the original all-in-one wrapper (reference score + performance file -> scoring result -> `frontend/viewer/public/result.json` -> starts the local viewer). Superseded for real practice sessions by `edge/practice_server.py`'s live guided-session flow, but still handy for grading a one-off file pair.
- `validate_grading_with_synthetic_errors.py`: synthesizes recordings with controlled, known mistakes (from keybank samples) to validate that the grading pipeline actually catches them -- a ground-truth check that doesn't depend on a real human performance.
- `validate_recording.sh`: 給組員用的一鍵驗證腳本 -- 選歌、給錄音檔，其餘（跑評分、開前端、開瀏覽器）全自動，不需要記任何 CLI 參數。

## Session Servers

- `session_server.py`: the SSH-based fallback orchestrator (dev machine <-> Raspberry Pi over SSH) for the same guided-practice flow `edge/practice_server.py` runs natively on the Pi -- use when the Pi doesn't have the grading dependencies installed. See its own module docstring and [frontend/viewer/README.md](../frontend/viewer/README.md) for the full API.

## Reference/Calibration Data

- `build_demo_audio_reference.py`: builds a `reference.json` directly from a demo recording (no MIDI/MusicXML), for the demo-audio-as-reference grading path.
- `synthesize_reference_from_keybank.py`: synthesizes a reference audio recording for a song by stitching together previously-recorded BF-3738C keybank note samples (per-measure synthesis, avoids buffer-mixing reverb bleed).
- `train_keybank_from_scale.py`: builds a BF-3738C keybank profile (one clean sample per key) from a single left-to-right scale recording.
- `train_keyboard_profile.py`: trains a lightweight keyboard timbre profile (used by `--keyboard-profile` in the grading scripts) from recordings.

## Hand-Posture Model Training

- `train_imu_from_session.py`: uses backend audio transcription/performance JSON
  to cut audio-triggered IMU windows, then trains a baseline classifier from
  all hand sensor streams for one session. It automatically uses `timing.json` from the session
  directory when available to align audio and IMU clocks. Output: `models/gesture/<session_id>_hand_imu_model.json`.
- `train_posture_from_sessions.py`: trains the **production** left-hand posture classifier (`models/gesture/left_hand_posture_classifier.joblib`/`.json`) from labeled session folders -- see [backend/sensors/README.md](../backend/sensors/README.md) for the labeling/data format this expects.
- `analyze_posture_predictions.py`: turns realtime `imu_predictions.jsonl`
  output into a posture scoring result. It writes a backend-style
  `posture_result.json` plus a readable `posture_result.md`:

  ```bash
  python3 scripts/analyze_posture_predictions.py \
    data/training_collection/artifacts/sessions/sess_posture_live_001/imu_predictions.jsonl
  ```

  The posture score is the confidence-weighted share of `normal` predictions.
  Consecutive high-confidence non-normal windows with the same label are merged
  into posture-error events with start/end times. (This is a standalone/offline
  analysis tool; the live-session equivalent baked into `edge/posture_capture.py`
  uses a simpler plain "% of windows classified normal" formula -- see
  `edge/README.md`.)

## Audio Utilities

- `filter_wav_noise.py`: filters simple microphone electrical hum from PCM `.wav`
  files. Example:

  ```bash
  python3 scripts/filter_wav_noise.py raw.wav clean.wav --mains 50
  ```

  Use `--mains 60` for 60 Hz power-line hum. Add `--gate` only when you want
  quiet gaps attenuated; for piano transcription, try the hum filter alone
  first so soft note tails are preserved.
