PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pieces (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    composer TEXT,
    reference_uri TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS practice_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    piece_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    target_bpm INTEGER,
    score REAL,
    summary_json TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    -- "learn" (LED-guided, lenient weights) or "perform" (no LED guidance,
    -- strict weights) -- both share the same scoring engine (backend.scoring),
    -- just different ScoringConfig weight presets. Nullable/no default so
    -- older rows written before this column existed (see init_db()'s
    -- defensive ALTER TABLE) are distinguishable from a genuine mode.
    mode TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (piece_id) REFERENCES pieces(id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    uri TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES practice_sessions(id)
);

CREATE TABLE IF NOT EXISTS model_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    input_artifact_id TEXT,
    output_artifact_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    metrics_json TEXT,
    FOREIGN KEY (session_id) REFERENCES practice_sessions(id),
    FOREIGN KEY (input_artifact_id) REFERENCES artifacts(id),
    FOREIGN KEY (output_artifact_id) REFERENCES artifacts(id)
);

CREATE INDEX IF NOT EXISTS idx_practice_sessions_user_started
ON practice_sessions (user_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_practice_sessions_piece
ON practice_sessions (piece_id);

CREATE INDEX IF NOT EXISTS idx_artifacts_session
ON artifacts (session_id);

CREATE INDEX IF NOT EXISTS idx_model_runs_session
ON model_runs (session_id);
