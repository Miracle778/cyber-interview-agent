CREATE TABLE review_question_batches_control (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    origin_session_id TEXT NOT NULL,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    source_refs_json TEXT NOT NULL,
    rewrite_of_batch_id TEXT REFERENCES review_question_batches_control(id),
    status TEXT NOT NULL CHECK (
        status IN (
            'generating', 'paused', 'interrupted', 'review_pending',
            'completed', 'failed', 'terminated'
        )
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    control_intent TEXT CHECK (control_intent IN ('pause', 'terminate')),
    concurrency_limit INTEGER NOT NULL DEFAULT 3 CHECK (
        concurrency_limit BETWEEN 1 AND 3
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO review_question_batches_control (
    id, workspace_id, session_id, origin_session_id, run_id,
    source_refs_json, rewrite_of_batch_id, status, created_at, updated_at
)
SELECT id, workspace_id, session_id, origin_session_id, run_id,
       source_refs_json, rewrite_of_batch_id, status, created_at, updated_at
FROM review_question_batches;

DROP TABLE review_question_batches;
ALTER TABLE review_question_batches_control RENAME TO review_question_batches;

CREATE INDEX idx_review_question_batches_workspace_status
    ON review_question_batches(workspace_id, status, updated_at DESC, id);
CREATE INDEX idx_review_question_batches_origin_session
    ON review_question_batches(origin_session_id, updated_at DESC, id);

CREATE TABLE review_curation_sessions_control (
    session_id TEXT PRIMARY KEY
        REFERENCES agent_sessions(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    source_refs_json TEXT NOT NULL CHECK (json_valid(source_refs_json)),
    active_batch_id TEXT
        REFERENCES review_question_batches(id) ON DELETE SET NULL,
    stage TEXT NOT NULL DEFAULT 'queued' CHECK (
        stage IN (
            'queued', 'reading_sources', 'generating', 'merging',
            'summarizing', 'waiting_for_command', 'publishing',
            'completed', 'failed', 'paused', 'interrupted', 'terminated'
        )
    ),
    completed_units INTEGER NOT NULL DEFAULT 0 CHECK (completed_units >= 0),
    total_units INTEGER NOT NULL DEFAULT 0 CHECK (total_units >= 0),
    summary_json TEXT NOT NULL DEFAULT '{"items":[]}' CHECK (
        json_valid(summary_json) AND json_type(summary_json) = 'object'
    ),
    summary_version INTEGER NOT NULL DEFAULT 0 CHECK (summary_version >= 0),
    warning_json TEXT NOT NULL DEFAULT '[]' CHECK (
        json_valid(warning_json) AND json_type(warning_json) = 'array'
    ),
    preferred_model_id TEXT,
    preferred_reasoning_effort TEXT NOT NULL DEFAULT 'none' CHECK (
        preferred_reasoning_effort IN ('none', 'low', 'medium', 'high')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (completed_units <= total_units OR total_units = 0)
);

INSERT INTO review_curation_sessions_control (
    session_id, workspace_id, source_refs_json, active_batch_id, stage,
    completed_units, total_units, summary_json, summary_version, warning_json,
    preferred_model_id, preferred_reasoning_effort, created_at, updated_at
)
SELECT session_id, workspace_id, source_refs_json, active_batch_id, stage,
       completed_units, total_units, summary_json, summary_version, warning_json,
       preferred_model_id, preferred_reasoning_effort, created_at, updated_at
FROM review_curation_sessions;

DROP TABLE review_curation_sessions;
ALTER TABLE review_curation_sessions_control RENAME TO review_curation_sessions;

CREATE INDEX idx_review_curation_sessions_workspace_updated
    ON review_curation_sessions(workspace_id, updated_at DESC, session_id);

CREATE TABLE review_curation_work_items_control (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES review_question_batches(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('discovery', 'enrichment')),
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

INSERT INTO review_curation_work_items_control (
    id, batch_id, stage, unit_index, input_digest, source_refs_json, status,
    output_json, attempt_count, last_error_code, created_at, updated_at
)
SELECT id, batch_id, stage, unit_index, input_digest, source_refs_json, status,
       output_json, attempt_count, last_error_code, created_at, updated_at
FROM review_curation_work_items;

DROP TABLE review_curation_work_items;
ALTER TABLE review_curation_work_items_control RENAME TO review_curation_work_items;

CREATE INDEX idx_review_curation_work_items_batch_stage_status
    ON review_curation_work_items(batch_id, stage, status, unit_index);

CREATE TABLE review_curation_batch_attempts (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES review_question_batches(id) ON DELETE CASCADE,
    execution_id TEXT NOT NULL UNIQUE REFERENCES agent_runs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    reason TEXT NOT NULL CHECK (
        reason IN ('initial', 'paused', 'failed', 'interrupted')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id, ordinal)
);

CREATE INDEX idx_review_curation_batch_attempts_batch_ordinal
    ON review_curation_batch_attempts(batch_id, ordinal, id);

CREATE TABLE review_curation_control_receipts (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES review_question_batches(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('pause', 'resume', 'terminate')),
    request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
    execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    result_status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id, idempotency_key)
);

CREATE INDEX idx_review_curation_control_receipts_batch_created
    ON review_curation_control_receipts(batch_id, created_at, id);
