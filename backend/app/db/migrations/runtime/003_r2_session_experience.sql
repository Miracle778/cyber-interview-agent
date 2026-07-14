ALTER TABLE agent_messages
    ADD COLUMN message_kind TEXT NOT NULL DEFAULT 'text' CHECK (
        message_kind IN (
            'text', 'stage', 'curation_summary', 'question_card',
            'review_prompt', 'review_answer', 'evaluation_card',
            'command_receipt', 'error'
        )
    );

ALTER TABLE agent_messages
    ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(payload_json) AND json_type(payload_json) = 'object'
    );

CREATE TABLE review_curation_sessions (
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
            'completed', 'failed'
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
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (completed_units <= total_units OR total_units = 0)
);

CREATE INDEX idx_review_curation_sessions_workspace_updated
    ON review_curation_sessions(workspace_id, updated_at DESC, session_id);

CREATE TABLE review_question_source_links (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    batch_id TEXT NOT NULL
        REFERENCES review_question_batches(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL
        REFERENCES agent_sessions(id) ON DELETE CASCADE,
    evidence_ref TEXT NOT NULL,
    merge_reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(question_id, source_id, evidence_ref)
);

CREATE INDEX idx_review_question_source_links_question
    ON review_question_source_links(question_id, created_at, id);
CREATE INDEX idx_review_question_source_links_source
    ON review_question_source_links(source_id, created_at, id);

ALTER TABLE review_attempts
    ADD COLUMN status TEXT NOT NULL DEFAULT 'completed' CHECK (
        status IN (
            'evaluating', 'waiting_for_follow_up',
            'completed', 'evaluation_failed'
        )
    );

ALTER TABLE review_attempts
    ADD COLUMN evaluation_error_code TEXT;

ALTER TABLE review_attempts
    ADD COLUMN evaluation_started_at TEXT;

ALTER TABLE review_attempts
    ADD COLUMN evaluation_completed_at TEXT;
