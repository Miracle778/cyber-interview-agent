ALTER TABLE agent_runs
    ADD COLUMN configuration_json TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(configuration_json) AND json_type(configuration_json) = 'object'
    );

ALTER TABLE agent_runs ADD COLUMN cancel_requested_at TEXT;

ALTER TABLE review_curation_command_receipts
    ADD COLUMN execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL;

ALTER TABLE review_curation_command_receipts
    ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'accepted' CHECK (
        lifecycle_status IN (
            'accepted', 'running', 'completed', 'partial_failure',
            'failed', 'cancelled', 'interrupted'
        )
    );

ALTER TABLE review_curation_sessions ADD COLUMN preferred_model_id TEXT;

ALTER TABLE review_curation_sessions
    ADD COLUMN preferred_reasoning_effort TEXT NOT NULL DEFAULT 'none' CHECK (
        preferred_reasoning_effort IN ('none', 'low', 'medium', 'high')
    );

CREATE TABLE review_bulk_publications (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL
        REFERENCES review_curation_sessions(session_id) ON DELETE CASCADE,
    execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    summary_version INTEGER NOT NULL CHECK (summary_version >= 0),
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'accepted' CHECK (
        status IN (
            'accepted', 'running', 'completed', 'partial_failure',
            'failed', 'cancelled', 'interrupted'
        )
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    UNIQUE(session_id, idempotency_key)
);

CREATE INDEX idx_review_bulk_publications_session_created
    ON review_bulk_publications(session_id, created_at, id);

CREATE TABLE review_bulk_publication_items (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL
        REFERENCES review_bulk_publications(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL
        REFERENCES review_question_candidates(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'skipped')
    ),
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(operation_id, candidate_id)
);

CREATE INDEX idx_review_bulk_publication_items_operation
    ON review_bulk_publication_items(operation_id, created_at, id);
