CREATE TABLE agent_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    graph_id TEXT NOT NULL,
    graph_version INTEGER NOT NULL CHECK (graph_version > 0),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN (
            'active',
            'waiting_for_approval',
            'interrupted',
            'completed',
            'migration_required',
            'archived'
        )
    ),
    parent_session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    summary TEXT,
    last_run_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_agent_sessions_workspace_updated
    ON agent_sessions(workspace_id, updated_at DESC);

CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (
        status IN (
            'queued',
            'running',
            'waiting_for_approval',
            'interrupted',
            'completed',
            'failed',
            'cancelled'
        )
    ),
    input_json TEXT NOT NULL DEFAULT '{}',
    model_bindings_json TEXT NOT NULL DEFAULT '{}',
    resume_count INTEGER NOT NULL DEFAULT 0 CHECK (resume_count >= 0),
    last_resumed_at TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX idx_agent_runs_session_created
    ON agent_runs(session_id, created_at DESC);

CREATE UNIQUE INDEX idx_agent_runs_one_active_per_session
    ON agent_runs(session_id)
    WHERE status IN ('queued', 'running', 'waiting_for_approval');

CREATE TABLE agent_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_agent_messages_session_created
    ON agent_messages(session_id, created_at, id);

CREATE TABLE agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, id)
);

CREATE INDEX idx_agent_events_session_id
    ON agent_events(session_id, id);
