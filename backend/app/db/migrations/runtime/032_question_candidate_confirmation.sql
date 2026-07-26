ALTER TABLE review_question_candidates
    ADD COLUMN confirmation_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        confirmation_status IN ('pending', 'confirmed')
    );

ALTER TABLE review_question_candidates
    ADD COLUMN confirmation_version INTEGER NOT NULL DEFAULT 0 CHECK (
        confirmation_version >= 0
    );

ALTER TABLE review_question_candidates
    ADD COLUMN confirmed_at TEXT;

CREATE TABLE review_candidate_confirmation_receipts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, idempotency_key)
);
