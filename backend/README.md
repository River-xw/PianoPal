# Backend

Reusable Python modules for PianoPal's score parsing, audio transcription, scoring, and validation pipeline.

Run commands from the repository root so imports resolve as `backend.*`.

```bash
python -m backend.score_to_reference score.musicxml -o reference.json
python -m backend.audio_to_performance recording.wav -o performance.json
python -m backend.scoring reference.json performance.json -o result.json
```

The current backend has no long-running API server yet. A future database/API service should live here and call these packages rather than duplicating their schemas.

## Local Data Layers

- `db/`: local SQLite index for users, pieces, practice sessions, artifact paths, and model-run metadata.
- `sensors/`: normalized hand IMU packet schemas, CSV parsing helpers, and keypress-window generation for Raspberry Pi acquisition.
