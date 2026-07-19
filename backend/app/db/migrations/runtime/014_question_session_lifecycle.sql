CREATE TABLE review_question_batches_lifecycle (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    origin_session_id TEXT NOT NULL,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    source_refs_json TEXT NOT NULL,
    rewrite_of_batch_id TEXT REFERENCES review_question_batches_lifecycle(id),
    status TEXT NOT NULL CHECK (
        status IN ('generating', 'review_pending', 'completed', 'failed')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO review_question_batches_lifecycle (
    id, workspace_id, session_id, origin_session_id, run_id,
    source_refs_json, rewrite_of_batch_id, status, created_at, updated_at
)
SELECT id, workspace_id, session_id, session_id, run_id,
       source_refs_json, rewrite_of_batch_id, status, created_at, updated_at
FROM review_question_batches;

DROP TABLE review_question_batches;
ALTER TABLE review_question_batches_lifecycle RENAME TO review_question_batches;

CREATE INDEX idx_review_question_batches_workspace_status
    ON review_question_batches(workspace_id, status, updated_at DESC, id);
CREATE INDEX idx_review_question_batches_origin_session
    ON review_question_batches(origin_session_id, updated_at DESC, id);

CREATE TABLE review_question_source_links_lifecycle (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    batch_id TEXT NOT NULL
        REFERENCES review_question_batches(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    origin_session_id TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    merge_reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(question_id, source_id, evidence_ref)
);

INSERT INTO review_question_source_links_lifecycle (
    id, question_id, source_id, batch_id, session_id, origin_session_id,
    evidence_ref, merge_reason, created_at, updated_at
)
SELECT id, question_id, source_id, batch_id, session_id, session_id,
       evidence_ref, merge_reason, created_at, updated_at
FROM review_question_source_links;

DROP TABLE review_question_source_links;
ALTER TABLE review_question_source_links_lifecycle
    RENAME TO review_question_source_links;

CREATE INDEX idx_review_question_source_links_question
    ON review_question_source_links(question_id, created_at, id);
CREATE INDEX idx_review_question_source_links_source
    ON review_question_source_links(source_id, created_at, id);
CREATE INDEX idx_review_question_source_links_origin_session
    ON review_question_source_links(origin_session_id, created_at, id);

ALTER TABLE review_question_candidates ADD COLUMN deleted_at TEXT;
ALTER TABLE review_question_candidates
    ADD COLUMN deletion_reason TEXT NOT NULL DEFAULT '';

CREATE INDEX idx_review_question_candidates_deleted
    ON review_question_candidates(deleted_at, updated_at DESC, id);

CREATE TABLE review_question_deletion_receipts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, idempotency_key)
);
