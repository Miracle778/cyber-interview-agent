CREATE TABLE review_curation_finalizations (
    batch_id TEXT PRIMARY KEY
        REFERENCES review_question_batches(id) ON DELETE CASCADE,
    execution_id TEXT NOT NULL
        REFERENCES agent_runs(id) ON DELETE CASCADE,
    batch_version INTEGER NOT NULL CHECK (batch_version > 0),
    state TEXT NOT NULL DEFAULT 'preparing' CHECK (
        state IN ('preparing', 'committed')
    ),
    candidate_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (
        json_valid(candidate_ids_json)
        AND json_type(candidate_ids_json) = 'array'
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_review_curation_finalizations_execution
    ON review_curation_finalizations(execution_id, state, updated_at, batch_id);
