# Backend

Reusable Python modules for PianoPal's score parsing, audio transcription, scoring, and validation pipeline.

Run commands from the repository root so imports resolve as `backend.*`.

```bash
python -m backend.score_to_reference score.musicxml -o reference.json
python -m backend.audio_to_performance recording.wav -o performance.json
python -m backend.scoring reference.json performance.json -o result.json
```

These `backend/*` packages are themselves still pure libraries/CLIs, no server of their own. The actual long-running practice-session API server is `edge/practice_server.py` (Pi-native) / `scripts/session_server.py` (SSH fallback) -- both import and call straight into `backend.db`, `backend.score_to_reference`, and shell out to `scripts/grade_audio_reference_constrained.py` (which in turn calls `backend.audio_to_performance` + `backend.scoring`), rather than duplicating any of this layer's schemas.

## Local Data Layers

- `db/`: local SQLite index for users, pieces, practice sessions, artifact paths, and model-run metadata.
- `sensors/`: normalized hand IMU packet schemas, CSV parsing helpers, and keypress-window generation for Raspberry Pi acquisition.
