BEGIN IMMEDIATE;

CREATE TABLE runtime_schema_metadata (
    generation INTEGER PRIMARY KEY CHECK (generation = 2),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO runtime_schema_metadata(generation) VALUES (2);

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
    title_source TEXT NOT NULL DEFAULT 'user' CHECK (
        title_source IN ('placeholder', 'generated', 'user')
    ),
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

CREATE TABLE tool_audits (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    error_code TEXT,
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    resource_scope TEXT,
    resource_path TEXT,
    resource_sha256 TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

CREATE INDEX idx_tool_audits_run_created ON tool_audits(run_id, created_at, id);

CREATE TABLE pending_actions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    preview_json TEXT NOT NULL,
    editable_fields_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'approved', 'edited_and_approved', 'rejected', 'cancelled')
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE INDEX idx_pending_actions_workspace_status_created
    ON pending_actions(workspace_id, status, created_at, id);
CREATE INDEX idx_pending_actions_session_status_created
    ON pending_actions(session_id, status, created_at, id);

CREATE TABLE pending_action_resolutions (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE REFERENCES pending_actions(id) ON DELETE CASCADE,
    resolution_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('approved', 'edited_and_approved', 'rejected')),
    decision_json TEXT NOT NULL,
    reason TEXT,
    delivery_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        delivery_status IN ('pending', 'delivering', 'delivered', 'failed')
    ),
    delivery_attempts INTEGER NOT NULL DEFAULT 0 CHECK (delivery_attempts >= 0),
    delivery_error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TEXT,
    UNIQUE(action_id, resolution_key)
);

CREATE INDEX idx_pending_action_resolutions_delivery
    ON pending_action_resolutions(delivery_status, created_at, id);

CREATE TABLE knowledge_drafts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    agent_type TEXT,
    domain TEXT NOT NULL,
    document_type TEXT NOT NULL CHECK (
        document_type IN ('source', 'question', 'concept', 'session_report', 'mastery_report')
    ),
    document_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content_path TEXT NOT NULL,
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    relation_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (
        status IN ('draft', 'review_pending', 'rejected', 'published')
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, content_path)
);

CREATE INDEX idx_knowledge_drafts_workspace_status_updated
    ON knowledge_drafts(workspace_id, status, updated_at DESC, id);

CREATE TABLE publication_runs (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE REFERENCES pending_actions(id) ON DELETE RESTRICT,
    draft_id TEXT NOT NULL REFERENCES knowledge_drafts(id) ON DELETE RESTRICT,
    expected_draft_version INTEGER NOT NULL CHECK (expected_draft_version > 0),
    expected_content_hash TEXT NOT NULL,
    document_id TEXT NOT NULL,
    target_path TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'prepared' CHECK (
        state IN ('prepared', 'file_written', 'indexed', 'completed', 'index_stale', 'failed')
    ),
    result_hash TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE INDEX idx_publication_runs_state_updated
    ON publication_runs(state, updated_at, id);

CREATE TABLE knowledge_sources (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    draft_id TEXT REFERENCES knowledge_drafts(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, stored_path)
);

CREATE INDEX idx_knowledge_sources_workspace_created
    ON knowledge_sources(workspace_id, created_at DESC, id DESC);

CREATE TABLE model_invocation_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    operation_key TEXT NOT NULL,
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    total_tokens INTEGER NOT NULL CHECK (total_tokens >= 0),
    estimated INTEGER NOT NULL CHECK (estimated IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, operation_key)
);

CREATE INDEX idx_model_invocation_usage_session
    ON model_invocation_usage(session_id, created_at, id);

CREATE TABLE runtime_guard_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    warning_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE runtime_warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMIT;
