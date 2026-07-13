CREATE TABLE model_invocation_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    operation_key TEXT NOT NULL,
    role TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    provider_model_id TEXT NOT NULL,
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    total_tokens INTEGER NOT NULL CHECK (total_tokens >= 0),
    context_tokens INTEGER NOT NULL CHECK (context_tokens >= 0),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    estimated INTEGER NOT NULL CHECK (estimated IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, operation_key)
);

CREATE INDEX idx_model_invocation_usage_session
    ON model_invocation_usage(session_id, created_at, id);

CREATE TABLE runtime_guard_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    kind TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    state_hash TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, sequence)
);

CREATE TABLE runtime_trace_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    segment_sequence INTEGER NOT NULL CHECK (segment_sequence > 0),
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    UNIQUE(run_id, segment_sequence)
);
