CREATE TABLE publication_runs_claimed (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE REFERENCES pending_actions(id) ON DELETE RESTRICT,
    draft_id TEXT NOT NULL REFERENCES knowledge_drafts(id) ON DELETE RESTRICT,
    expected_draft_version INTEGER NOT NULL CHECK (expected_draft_version > 0),
    expected_content_hash TEXT NOT NULL,
    document_id TEXT NOT NULL,
    target_path TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'prepared' CHECK (
        state IN (
            'prepared', 'file_written', 'committing', 'compensating',
            'indexed', 'completed', 'index_stale', 'failed', 'revoked'
        )
    ),
    result_hash TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

INSERT INTO publication_runs_claimed (
    id, action_id, draft_id, expected_draft_version, expected_content_hash,
    document_id, target_path, state, result_hash, error_code,
    created_at, updated_at, completed_at
)
SELECT
    id, action_id, draft_id, expected_draft_version, expected_content_hash,
    document_id, target_path, state, result_hash, error_code,
    created_at, updated_at, completed_at
FROM publication_runs;

DROP TABLE publication_runs;
ALTER TABLE publication_runs_claimed RENAME TO publication_runs;

CREATE INDEX idx_publication_runs_state_updated
    ON publication_runs(state, updated_at, id);
