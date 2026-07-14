CREATE TABLE review_curation_command_receipts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL
        REFERENCES review_curation_sessions(session_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    summary_version INTEGER NOT NULL CHECK (summary_version >= 0),
    command_json TEXT NOT NULL CHECK (
        json_valid(command_json) AND json_type(command_json) = 'object'
    ),
    result_json TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(result_json) AND json_type(result_json) = 'object'
    ),
    status TEXT NOT NULL DEFAULT 'processing' CHECK (
        status IN ('processing', 'completed', 'partial_failure', 'failed')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    UNIQUE(session_id, idempotency_key)
);

CREATE INDEX idx_review_curation_command_receipts_session_created
    ON review_curation_command_receipts(session_id, created_at, id);
