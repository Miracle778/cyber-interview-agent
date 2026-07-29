CREATE TABLE agent_trace_files (
    relative_path TEXT PRIMARY KEY,
    scanned_bytes INTEGER NOT NULL DEFAULT 0 CHECK (scanned_bytes >= 0),
    last_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    file_size INTEGER NOT NULL DEFAULT 0 CHECK (file_size >= 0),
    file_mtime_ns INTEGER NOT NULL DEFAULT 0 CHECK (file_mtime_ns >= 0),
    health TEXT NOT NULL DEFAULT 'complete' CHECK (
        health IN ('complete', 'partial', 'missing')
    ),
    malformed_rows INTEGER NOT NULL DEFAULT 0 CHECK (malformed_rows >= 0),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_trace_executions (
    run_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    first_event_at TEXT,
    last_event_at TEXT,
    trace_health TEXT NOT NULL DEFAULT 'complete' CHECK (
        trace_health IN ('complete', 'partial', 'missing')
    ),
    indexed_event_count INTEGER NOT NULL DEFAULT 0 CHECK (indexed_event_count >= 0),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_agent_trace_executions_workspace_last_event
    ON agent_trace_executions(workspace_id, last_event_at DESC, run_id);

CREATE TABLE agent_trace_operations (
    operation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_operation_id TEXT,
    kind TEXT NOT NULL CHECK (
        kind IN ('execution', 'agent', 'model', 'tool', 'graph')
    ),
    name TEXT NOT NULL,
    agent_role TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT,
    finished_at TEXT,
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    error_code TEXT,
    FOREIGN KEY(run_id) REFERENCES agent_trace_executions(run_id) ON DELETE CASCADE,
    FOREIGN KEY(parent_operation_id) REFERENCES agent_trace_operations(operation_id)
        ON DELETE SET NULL
);

CREATE INDEX idx_agent_trace_operations_run_parent
    ON agent_trace_operations(run_id, parent_operation_id, started_at, operation_id);

CREATE TABLE agent_trace_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    observed_at TEXT,
    relative_path TEXT NOT NULL,
    byte_start INTEGER NOT NULL CHECK (byte_start >= 0),
    byte_length INTEGER NOT NULL CHECK (byte_length > 0),
    payload_sha256 TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    FOREIGN KEY(run_id) REFERENCES agent_trace_executions(run_id) ON DELETE CASCADE,
    FOREIGN KEY(operation_id) REFERENCES agent_trace_operations(operation_id)
        ON DELETE CASCADE,
    FOREIGN KEY(relative_path) REFERENCES agent_trace_files(relative_path)
        ON DELETE CASCADE
);

CREATE INDEX idx_agent_trace_events_run_sequence
    ON agent_trace_events(run_id, sequence, event_id);

CREATE INDEX idx_agent_trace_events_operation_sequence
    ON agent_trace_events(operation_id, sequence, event_id);
