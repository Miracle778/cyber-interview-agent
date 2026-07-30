CREATE TABLE agent_trace_retention_policy (
    workspace_id TEXT PRIMARY KEY,
    body_policy TEXT NOT NULL DEFAULT 'days' CHECK (
        body_policy IN ('permanent', 'days', 'metadata_only')
    ),
    body_days INTEGER CHECK (
        (body_policy = 'days' AND body_days BETWEEN 1 AND 3650)
        OR (body_policy != 'days' AND body_days IS NULL)
    ),
    metadata_policy TEXT NOT NULL DEFAULT 'retain' CHECK (
        metadata_policy = 'retain'
    ),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_trace_cleanup_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned' CHECK (
        status IN (
            'planned', 'quarantining', 'quarantined', 'finalizing',
            'completed', 'partial_failure', 'failed'
        )
    ),
    file_count INTEGER NOT NULL DEFAULT 0 CHECK (file_count >= 0),
    event_count INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0),
    total_bytes INTEGER NOT NULL DEFAULT 0 CHECK (total_bytes >= 0),
    protected_active_runs INTEGER NOT NULL DEFAULT 0 CHECK (
        protected_active_runs >= 0
    ),
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TEXT,
    completed_at TEXT,
    UNIQUE(workspace_id, request_hash)
);

CREATE TABLE agent_trace_cleanup_items (
    cleanup_id TEXT NOT NULL REFERENCES agent_trace_cleanup_runs(id)
        ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    quarantine_relative_path TEXT,
    run_id TEXT NOT NULL,
    event_count INTEGER NOT NULL CHECK (event_count >= 0),
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    status TEXT NOT NULL DEFAULT 'planned' CHECK (
        status IN ('planned', 'quarantined', 'finalized', 'failed')
    ),
    error_code TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(cleanup_id, relative_path)
);

CREATE TABLE agent_trace_projection_deliveries (
    delivery_key TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    operation_id TEXT,
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'completed', 'failed')
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE agent_trace_events
    ADD COLUMN body_state TEXT NOT NULL DEFAULT 'available' CHECK (
        body_state IN ('available', 'quarantined', 'deleted', 'unavailable')
    );

CREATE INDEX idx_trace_cleanup_workspace_created
    ON agent_trace_cleanup_runs(workspace_id, created_at DESC);
CREATE INDEX idx_trace_projection_workspace_run
    ON agent_trace_projection_deliveries(workspace_id, run_id);
