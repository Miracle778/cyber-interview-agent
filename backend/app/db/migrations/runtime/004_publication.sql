CREATE TABLE knowledge_drafts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    agent_type TEXT,
    domain TEXT NOT NULL,
    document_type TEXT NOT NULL CHECK (
        document_type IN (
            'source',
            'question',
            'concept',
            'session_report',
            'mastery_report'
        )
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
    action_id TEXT NOT NULL UNIQUE
        REFERENCES pending_actions(id) ON DELETE RESTRICT,
    draft_id TEXT NOT NULL
        REFERENCES knowledge_drafts(id) ON DELETE RESTRICT,
    expected_draft_version INTEGER NOT NULL CHECK (expected_draft_version > 0),
    expected_content_hash TEXT NOT NULL,
    document_id TEXT NOT NULL,
    target_path TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'prepared' CHECK (
        state IN (
            'prepared',
            'file_written',
            'indexed',
            'completed',
            'index_stale',
            'failed'
        )
    ),
    result_hash TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE INDEX idx_publication_runs_state_updated
    ON publication_runs(state, updated_at, id);
