CREATE TABLE review_curation_staged_drafts (
    draft_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    content_path TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_review_curation_staged_drafts_owner
    ON review_curation_staged_drafts(batch_id, execution_id, created_at, draft_id);
