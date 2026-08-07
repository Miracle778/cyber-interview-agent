CREATE TABLE review_curation_work_items_audit (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES review_question_batches(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('discovery', 'audit', 'enrichment')),
    unit_index INTEGER NOT NULL CHECK (unit_index >= 0),
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    source_refs_json TEXT NOT NULL CHECK (
        json_valid(source_refs_json) AND json_type(source_refs_json) = 'array'
    ),
    processor_kind TEXT NOT NULL DEFAULT 'model' CHECK (
        processor_kind IN ('deterministic', 'model')
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'interrupted')
    ),
    output_json TEXT CHECK (output_json IS NULL OR json_valid(output_json)),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id, stage, unit_index)
);

INSERT INTO review_curation_work_items_audit (
    id, batch_id, stage, unit_index, input_digest, source_refs_json,
    processor_kind, status, output_json, attempt_count, last_error_code,
    created_at, updated_at
)
SELECT id, batch_id, stage, unit_index, input_digest, source_refs_json,
       processor_kind, status, output_json, attempt_count, last_error_code,
       created_at, updated_at
FROM review_curation_work_items;

DROP TABLE review_curation_work_items;
ALTER TABLE review_curation_work_items_audit RENAME TO review_curation_work_items;

CREATE INDEX idx_review_curation_work_items_batch_stage_status
    ON review_curation_work_items(batch_id, stage, status, unit_index);
