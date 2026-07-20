# Local SQLite DB

This package provides PianoPal's local structured database layer.

SQLite stores the lightweight index:

- users
- pieces
- practice sessions
- artifact file paths
- model run metadata

Large files should stay in `data/raw/` or `data/artifacts/`; ChromaDB should
store searchable summaries, feature vectors, labels, and user-profile memory.

## Initialize

Run from the repository root:

```bash
python -c "from backend.db import init_db; init_db()"
```

This creates:

```text
data/db/pianopal.sqlite3
```

## Example

```python
from backend.db import (
    add_artifact,
    create_piece,
    create_practice_session,
    create_user,
    finish_practice_session,
    init_db,
)

init_db()
create_user("u_local_001", "River", "2026-07-20T10:30:00+08:00")
create_piece(
    "piece_fur_elise",
    "Fur Elise",
    "Beethoven",
    "data/artifacts/pieces/piece_fur_elise/reference.json",
    "2026-07-20T10:30:00+08:00",
)
create_practice_session(
    "sess_20260720_001",
    "u_local_001",
    "piece_fur_elise",
    "2026-07-20T10:31:00+08:00",
    target_bpm=80,
)
add_artifact(
    "artifact_sess_001_result",
    "sess_20260720_001",
    "scoring_result",
    "data/artifacts/sessions/sess_20260720_001/result.json",
    "2026-07-20T10:35:00+08:00",
)
finish_practice_session(
    "sess_20260720_001",
    "2026-07-20T10:36:00+08:00",
    82.5,
    {"score": 82.5, "counts": {"correct": 120}},
)
```
