ALTER TABLE interview_cleanup_versions
    ADD COLUMN document_body TEXT;

ALTER TABLE interview_cleanup_versions
    ADD COLUMN document_sha256 TEXT
        CHECK (document_sha256 IS NULL OR length(document_sha256) = 64);

CREATE TABLE interview_transcript_review_issues (
    id TEXT PRIMARY KEY,
    cleanup_version_id TEXT NOT NULL
        REFERENCES interview_cleanup_versions(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    document_start INTEGER NOT NULL CHECK (document_start >= 0),
    document_end INTEGER NOT NULL CHECK (document_end > document_start),
    excerpt TEXT NOT NULL,
    suggestion TEXT,
    issue_kind TEXT NOT NULL
        CHECK (issue_kind IN ('uncertain_term', 'speaker', 'semantic')),
    reason TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    decision TEXT NOT NULL DEFAULT 'pending'
        CHECK (decision IN ('pending', 'accepted', 'kept', 'manual')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cleanup_version_id, ordinal)
);

CREATE INDEX idx_interview_transcript_review_issues_order
    ON interview_transcript_review_issues(cleanup_version_id, ordinal, id);
