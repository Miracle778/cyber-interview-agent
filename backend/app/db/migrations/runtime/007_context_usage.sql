CREATE TABLE agent_context_usage (
    session_id TEXT PRIMARY KEY REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    current_tokens INTEGER NOT NULL CHECK (current_tokens >= 0),
    threshold_tokens INTEGER NOT NULL CHECK (threshold_tokens > 0),
    estimated INTEGER NOT NULL CHECK (estimated IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
