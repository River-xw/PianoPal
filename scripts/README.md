# Scripts

Developer-facing wrappers around the main pipeline.

- `grade.py`: converts a reference score and a performance file into a scoring result, writes it to `frontend/viewer/public/result.json`, and starts the local viewer.
- `filter_wav_noise.py`: filters simple microphone electrical hum from PCM `.wav`
  files. Example:

  ```bash
  python3 scripts/filter_wav_noise.py raw.wav clean.wav --mains 50
  ```

  Use `--mains 60` for 60 Hz power-line hum. Add `--gate` only when you want
  quiet gaps attenuated; for piano transcription, try the hum filter alone
  first so soft note tails are preserved.
