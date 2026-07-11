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
        status IN (
            'pending',
            'approved',
            'edited_and_approved',
            'rejected',
            'cancelled'
        )
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
    action_id TEXT NOT NULL UNIQUE
        REFERENCES pending_actions(id) ON DELETE CASCADE,
    resolution_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('approved', 'edited_and_approved', 'rejected')
    ),
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
