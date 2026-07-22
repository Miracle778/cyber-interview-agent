CREATE TABLE review_curation_seed_tasks (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL
        REFERENCES review_question_batches(id) ON DELETE CASCADE,
    discovery_work_item_id TEXT NOT NULL
        REFERENCES review_curation_work_items(id) ON DELETE CASCADE,
    seed_key TEXT NOT NULL CHECK (
        length(seed_key) = 64 AND seed_key NOT GLOB '*[^0-9a-f]*'
    ),
    seed_ordinal INTEGER NOT NULL CHECK (seed_ordinal >= 0),
    question_text TEXT NOT NULL CHECK (length(trim(question_text)) > 0),
    primary_source_ref TEXT NOT NULL CHECK (
        length(trim(primary_source_ref)) > 0
    ),
    source_refs_json TEXT NOT NULL CHECK (
        json_valid(source_refs_json) AND json_type(source_refs_json) = 'array'
    ),
    input_digest TEXT NOT NULL CHECK (
        length(input_digest) = 64 AND input_digest NOT GLOB '*[^0-9a-f]*'
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending', 'running', 'completed', 'degraded',
            'retryable', 'interrupted', 'skipped'
        )
    ),
    automatic_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (
        automatic_attempt_count BETWEEN 0 AND 2
    ),
    manual_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (
        manual_attempt_count >= 0
    ),
    candidate_json TEXT CHECK (
        candidate_json IS NULL OR (
            json_valid(candidate_json) AND json_type(candidate_json) = 'object'
        )
    ),
    answer_basis TEXT NOT NULL DEFAULT 'unknown' CHECK (
        answer_basis IN ('source', 'mixed', 'model', 'unknown')
    ),
    material_support TEXT NOT NULL DEFAULT 'unknown' CHECK (
        material_support IN ('sufficient', 'partial', 'minimal', 'unknown')
    ),
    needs_review INTEGER NOT NULL DEFAULT 1 CHECK (needs_review IN (0, 1)),
    normalization_issues_json TEXT NOT NULL DEFAULT '[]' CHECK (
        json_valid(normalization_issues_json)
        AND json_type(normalization_issues_json) = 'array'
    ),
    last_error_code TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX ux_review_curation_seed_tasks_batch_key
    ON review_curation_seed_tasks(batch_id, seed_key);
CREATE INDEX idx_review_curation_seed_tasks_batch_status_ordinal
    ON review_curation_seed_tasks(batch_id, status, seed_ordinal);

CREATE TABLE review_curation_seed_retry_receipts (
    id TEXT PRIMARY KEY,
    seed_task_id TEXT NOT NULL
        REFERENCES review_curation_seed_tasks(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL CHECK (
        length(trim(idempotency_key)) > 0 AND length(idempotency_key) <= 200
    ),
    request_digest TEXT NOT NULL CHECK (
        length(request_digest) = 64
        AND request_digest NOT GLOB '*[^0-9a-f]*'
    ),
    execution_id TEXT NOT NULL
        REFERENCES agent_runs(id) ON DELETE RESTRICT,
    result_status TEXT NOT NULL DEFAULT 'accepted' CHECK (
        result_status IN (
            'accepted', 'running', 'completed', 'degraded',
            'retryable', 'interrupted', 'skipped', 'failed'
        )
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(seed_task_id, idempotency_key)
);

CREATE INDEX idx_review_curation_seed_retry_receipts_seed_created
    ON review_curation_seed_retry_receipts(seed_task_id, created_at, id);

ALTER TABLE review_question_candidates
    ADD COLUMN seed_task_id TEXT
        REFERENCES review_curation_seed_tasks(id) ON DELETE SET NULL;
ALTER TABLE review_question_candidates
    ADD COLUMN answer_basis TEXT NOT NULL DEFAULT 'unknown' CHECK (
        answer_basis IN ('source', 'mixed', 'model', 'unknown')
    );
ALTER TABLE review_question_candidates
    ADD COLUMN material_support TEXT NOT NULL DEFAULT 'unknown' CHECK (
        material_support IN ('sufficient', 'partial', 'minimal', 'unknown')
    );
ALTER TABLE review_question_candidates
    ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 1 CHECK (
        needs_review IN (0, 1)
    );
ALTER TABLE review_question_candidates
    ADD COLUMN normalization_issues_json TEXT NOT NULL
        DEFAULT '["legacy_quality_unknown"]' CHECK (
            json_valid(normalization_issues_json)
            AND json_type(normalization_issues_json) = 'array'
        );

CREATE UNIQUE INDEX ux_review_question_candidates_seed_task
    ON review_question_candidates(seed_task_id)
    WHERE seed_task_id IS NOT NULL;
