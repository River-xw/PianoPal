# Scripts

Developer-facing wrappers around the main pipeline.

- `grade.py`: converts a reference score and a performance file into a scoring result, writes it to `frontend/viewer/public/result.json`, and starts the local viewer.
- `train_imu_from_session.py`: uses backend audio transcription/performance JSON
  to cut audio-triggered IMU windows, then trains a baseline classifier from
  all hand sensor streams. It automatically uses `timing.json` from the session
  directory when available to align audio and IMU clocks.
- `analyze_posture_predictions.py`: turns realtime `imu_predictions.jsonl`
  output into a posture scoring result. It writes a backend-style
  `posture_result.json` plus a readable `posture_result.md`:

  ```bash
  python3 scripts/analyze_posture_predictions.py \
    data/artifacts/sessions/sess_posture_live_001/imu_predictions.jsonl
  ```

  The posture score is the confidence-weighted share of `normal` predictions.
  Consecutive high-confidence non-normal windows with the same label are merged
  into posture-error events with start/end times.
- `filter_wav_noise.py`: filters simple microphone electrical hum from PCM `.wav`
  files. Example:

  ```bash
  python3 scripts/filter_wav_noise.py raw.wav clean.wav --mains 50
  ```

  Use `--mains 60` for 60 Hz power-line hum. Add `--gate` only when you want
  quiet gaps attenuated; for piano transcription, try the hum filter alone
  first so soft note tails are preserved.
