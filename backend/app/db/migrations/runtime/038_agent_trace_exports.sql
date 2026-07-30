CREATE TABLE agent_trace_exports (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'completed', 'failed')
    ),
    artifact_relative_path TEXT,
    artifact_sha256 TEXT,
    metadata_only INTEGER NOT NULL CHECK (metadata_only IN (0, 1)),
    includes_bodies INTEGER NOT NULL CHECK (includes_bodies IN (0, 1)),
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    UNIQUE(workspace_id, idempotency_key)
);

CREATE INDEX idx_agent_trace_exports_run_created
    ON agent_trace_exports(workspace_id, run_id, created_at DESC);
