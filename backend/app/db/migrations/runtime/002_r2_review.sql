CREATE TABLE agent_sessions_r2 (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    graph_id TEXT NOT NULL,
    graph_version INTEGER NOT NULL CHECK (graph_version > 0),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN (
            'active',
            'waiting_for_input',
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

INSERT INTO agent_sessions_r2
SELECT * FROM agent_sessions;
DROP TABLE agent_sessions;
ALTER TABLE agent_sessions_r2 RENAME TO agent_sessions;

CREATE INDEX idx_agent_sessions_workspace_updated
    ON agent_sessions(workspace_id, updated_at DESC);

CREATE TABLE agent_runs_r2 (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (
        status IN (
            'queued',
            'running',
            'waiting_for_input',
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

INSERT INTO agent_runs_r2
SELECT * FROM agent_runs;
DROP TABLE agent_runs;
ALTER TABLE agent_runs_r2 RENAME TO agent_runs;

CREATE INDEX idx_agent_runs_session_created
    ON agent_runs(session_id, created_at DESC);
CREATE UNIQUE INDEX idx_agent_runs_one_active_per_session
    ON agent_runs(session_id)
    WHERE status IN (
        'queued', 'running', 'waiting_for_input', 'waiting_for_approval'
    );

CREATE TABLE review_question_batches (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    source_refs_json TEXT NOT NULL,
    rewrite_of_batch_id TEXT REFERENCES review_question_batches(id),
    status TEXT NOT NULL CHECK (
        status IN ('generating', 'review_pending', 'completed', 'failed')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_review_question_batches_workspace_status
    ON review_question_batches(workspace_id, status, updated_at DESC, id);

CREATE TABLE review_question_candidates (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES review_question_batches(id) ON DELETE CASCADE,
    draft_id TEXT UNIQUE REFERENCES knowledge_drafts(id) ON DELETE SET NULL,
    question_json TEXT NOT NULL,
    duplicate_of_question_id TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('draft', 'review_pending', 'rejected', 'published')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_review_question_candidates_batch_status
    ON review_question_candidates(batch_id, status, updated_at DESC, id);

CREATE TABLE review_question_catalog (
    question_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    draft_id TEXT NOT NULL UNIQUE REFERENCES knowledge_drafts(id) ON DELETE RESTRICT,
    publication_id TEXT NOT NULL UNIQUE REFERENCES publication_runs(id) ON DELETE RESTRICT,
    question_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    published_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_review_question_catalog_workspace_active
    ON review_question_catalog(workspace_id, active, updated_at DESC, question_id);

CREATE TABLE review_rounds (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE REFERENCES agent_sessions(id) ON DELETE CASCADE,
    execution_id TEXT UNIQUE REFERENCES agent_runs(id) ON DELETE SET NULL,
    settings_json TEXT NOT NULL,
    question_snapshots_json TEXT NOT NULL,
    mastery_before_json TEXT NOT NULL DEFAULT '{}',
    current_index INTEGER NOT NULL DEFAULT 0 CHECK (current_index >= 0),
    status TEXT NOT NULL CHECK (
        status IN (
            'waiting_for_input', 'running', 'report_pending',
            'completed', 'failed', 'cancelled'
        )
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE INDEX idx_review_rounds_workspace_updated
    ON review_rounds(workspace_id, updated_at DESC, id);

CREATE TABLE review_report_proposals (
    draft_id TEXT PRIMARY KEY REFERENCES knowledge_drafts(id) ON DELETE CASCADE,
    round_id TEXT NOT NULL REFERENCES review_rounds(id) ON DELETE CASCADE,
    report_kind TEXT NOT NULL CHECK (
        report_kind IN ('session_report', 'mastery_report')
    ),
    proposal_json TEXT NOT NULL,
    expected_mastery_version INTEGER CHECK (
        expected_mastery_version IS NULL OR expected_mastery_version >= 0
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(round_id, report_kind, draft_id)
);

CREATE TABLE review_attempts (
    id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES review_rounds(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    question_snapshot_json TEXT NOT NULL,
    answer TEXT,
    follow_up_answer TEXT,
    evaluation_json TEXT,
    mastery_suggestion TEXT CHECK (
        mastery_suggestion IS NULL OR mastery_suggestion IN (
            'weak', 'partial', 'stable', 'strong'
        )
    ),
    skipped INTEGER NOT NULL DEFAULT 0 CHECK (skipped IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(round_id, ordinal)
);

CREATE TABLE review_input_requests (
    id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES review_rounds(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    kind TEXT NOT NULL CHECK (kind IN ('answer', 'follow_up')),
    prompt TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'resolved', 'cancelled')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    UNIQUE(round_id, ordinal, kind, version)
);

CREATE INDEX idx_review_input_requests_round_status
    ON review_input_requests(round_id, status, created_at, id);

CREATE TABLE review_input_receipts (
    id TEXT PRIMARY KEY,
    input_request_id TEXT NOT NULL UNIQUE
        REFERENCES review_input_requests(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(input_request_id, idempotency_key)
);

CREATE TABLE review_mastery_projection (
    workspace_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    projection_json TEXT NOT NULL DEFAULT '{}',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
