-- Versioned interview retrospectives, resumable processing, and controlled
-- cross-domain candidate receipts.

CREATE TABLE interview_retrospectives (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    round_label TEXT NOT NULL,
    interview_date TEXT,
    outcome TEXT NOT NULL DEFAULT 'unrecorded'
        CHECK (outcome IN ('pending', 'passed', 'failed', 'cancelled', 'unrecorded')),
    note TEXT NOT NULL DEFAULT '',
    lifecycle_status TEXT NOT NULL DEFAULT 'active'
        CHECK (lifecycle_status IN ('active', 'archived', 'recycled')),
    active_source_version_id TEXT
        REFERENCES interview_source_versions(id) ON DELETE SET NULL,
    active_cleanup_version_id TEXT
        REFERENCES interview_cleanup_versions(id) ON DELETE SET NULL,
    active_analysis_run_id TEXT
        REFERENCES interview_analysis_runs(id) ON DELETE SET NULL,
    analysis_session_id TEXT NOT NULL UNIQUE
        REFERENCES agent_sessions(id) ON DELETE CASCADE,
    chat_session_id TEXT NOT NULL UNIQUE
        REFERENCES agent_sessions(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_interview_retrospectives_workspace_lifecycle
    ON interview_retrospectives(
        workspace_id, lifecycle_status, updated_at DESC, id
    );
CREATE INDEX idx_interview_retrospectives_target_date
    ON interview_retrospectives(
        job_target_id, interview_date DESC, created_at DESC, id
    );

CREATE TABLE interview_source_versions (
    id TEXT PRIMARY KEY,
    retrospective_id TEXT NOT NULL
        REFERENCES interview_retrospectives(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    source_kind TEXT NOT NULL
        CHECK (source_kind IN ('transcript', 'recollection')),
    file_name TEXT,
    body TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    cleared_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(retrospective_id, ordinal)
);
CREATE INDEX idx_interview_sources_retrospective
    ON interview_source_versions(retrospective_id, ordinal DESC, id);

CREATE TABLE interview_cleanup_versions (
    id TEXT PRIMARY KEY,
    retrospective_id TEXT NOT NULL
        REFERENCES interview_retrospectives(id) ON DELETE CASCADE,
    source_version_id TEXT NOT NULL
        REFERENCES interview_source_versions(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN (
            'queued', 'running', 'stopping', 'stopped',
            'review_pending', 'confirmed', 'failed'
        )),
    stage TEXT NOT NULL DEFAULT 'normalizing'
        CHECK (stage IN (
            'normalizing', 'cleaning', 'reducing', 'waiting_for_review',
            'confirmed', 'stopped', 'failed'
        )),
    control_intent TEXT CHECK (control_intent IN ('stop')),
    confirmed_at TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(retrospective_id, ordinal)
);
CREATE UNIQUE INDEX ux_interview_cleanup_active
    ON interview_cleanup_versions(retrospective_id)
    WHERE status IN ('queued', 'running', 'stopping');
CREATE INDEX idx_interview_cleanup_source
    ON interview_cleanup_versions(source_version_id, ordinal DESC, id);

CREATE TABLE interview_cleanup_work_items (
    id TEXT PRIMARY KEY,
    cleanup_version_id TEXT NOT NULL
        REFERENCES interview_cleanup_versions(id) ON DELETE CASCADE,
    work_key TEXT NOT NULL,
    source_start INTEGER NOT NULL CHECK (source_start >= 0),
    source_end INTEGER NOT NULL CHECK (source_end > source_start),
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'running', 'completed', 'retryable',
            'interrupted', 'skipped'
        )),
    output_json TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cleanup_version_id, work_key)
);
CREATE INDEX idx_interview_cleanup_items_status
    ON interview_cleanup_work_items(
        cleanup_version_id, status, source_start, id
    );

CREATE TABLE interview_segments (
    id TEXT PRIMARY KEY,
    cleanup_version_id TEXT NOT NULL
        REFERENCES interview_cleanup_versions(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    speaker_role TEXT NOT NULL
        CHECK (speaker_role IN ('candidate', 'interviewer', 'unknown')),
    raw_speaker_label TEXT,
    display_name TEXT NOT NULL,
    body TEXT NOT NULL,
    source_start INTEGER NOT NULL CHECK (source_start >= 0),
    source_end INTEGER NOT NULL CHECK (source_end > source_start),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    uncertainty_reason TEXT,
    ignored INTEGER NOT NULL DEFAULT 0 CHECK (ignored IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cleanup_version_id, ordinal)
);
CREATE INDEX idx_interview_segments_order
    ON interview_segments(cleanup_version_id, ordinal, id);

CREATE TABLE interview_question_units (
    id TEXT PRIMARY KEY,
    retrospective_id TEXT NOT NULL
        REFERENCES interview_retrospectives(id) ON DELETE CASCADE,
    cleanup_version_id TEXT NOT NULL
        REFERENCES interview_cleanup_versions(id) ON DELETE CASCADE,
    stable_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    question_kind TEXT NOT NULL
        CHECK (question_kind IN (
            'technical_knowledge', 'project_experience', 'system_design',
            'behavioral_collaboration', 'motivation_hr', 'unknown'
        )),
    origin TEXT NOT NULL CHECK (origin IN ('original', 'inferred')),
    question_text TEXT NOT NULL,
    question_segment_ids_json TEXT NOT NULL DEFAULT '[]',
    answer_segment_ids_json TEXT NOT NULL DEFAULT '[]',
    inference_basis TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    decision_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (decision_status IN (
            'pending', 'confirmed', 'rejected', 'superseded'
        )),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cleanup_version_id, stable_key),
    UNIQUE(cleanup_version_id, ordinal)
);
CREATE INDEX idx_interview_questions_order
    ON interview_question_units(
        retrospective_id, cleanup_version_id, ordinal, id
    );

CREATE TABLE interview_analysis_runs (
    id TEXT PRIMARY KEY,
    retrospective_id TEXT NOT NULL
        REFERENCES interview_retrospectives(id) ON DELETE CASCADE,
    cleanup_version_id TEXT NOT NULL
        REFERENCES interview_cleanup_versions(id) ON DELETE RESTRICT,
    execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    retry_of_analysis_run_id TEXT
        REFERENCES interview_analysis_runs(id) ON DELETE SET NULL,
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    context_snapshot_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN (
            'queued', 'running', 'stopping', 'stopped',
            'review_pending', 'completed', 'failed'
        )),
    stage TEXT NOT NULL DEFAULT 'question_extraction'
        CHECK (stage IN (
            'question_extraction', 'analyzing_questions', 'verifying_gaps',
            'generating_candidates', 'finalizing', 'review_pending',
            'completed', 'stopped', 'failed'
        )),
    control_intent TEXT CHECK (control_intent IN ('stop')),
    completed_items INTEGER NOT NULL DEFAULT 0 CHECK (completed_items >= 0),
    total_items INTEGER NOT NULL DEFAULT 0 CHECK (total_items >= 0),
    current_work_key TEXT,
    cumulative_elapsed_ms INTEGER NOT NULL DEFAULT 0
        CHECK (cumulative_elapsed_ms >= 0),
    latest_progress_at TEXT,
    summary_json TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX ux_interview_analysis_active
    ON interview_analysis_runs(retrospective_id)
    WHERE status IN ('queued', 'running', 'stopping');
CREATE INDEX idx_interview_analysis_history
    ON interview_analysis_runs(retrospective_id, created_at DESC, id);

CREATE TABLE interview_analysis_work_items (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL
        REFERENCES interview_analysis_runs(id) ON DELETE CASCADE,
    question_unit_id TEXT
        REFERENCES interview_question_units(id) ON DELETE CASCADE,
    work_key TEXT NOT NULL,
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'running', 'completed', 'retryable',
            'interrupted', 'skipped', 'blocked'
        )),
    output_json TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(analysis_run_id, work_key)
);
CREATE INDEX idx_interview_analysis_items_status
    ON interview_analysis_work_items(
        analysis_run_id, status, updated_at, id
    );

CREATE TABLE interview_question_analyses (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL
        REFERENCES interview_analysis_runs(id) ON DELETE CASCADE,
    question_unit_id TEXT NOT NULL
        REFERENCES interview_question_units(id) ON DELETE CASCADE,
    verdict TEXT NOT NULL
        CHECK (verdict IN (
            'strong', 'improvable', 'high_risk', 'insufficient_evidence'
        )),
    strengths_json TEXT NOT NULL DEFAULT '[]',
    improvements_json TEXT NOT NULL DEFAULT '[]',
    omissions_json TEXT NOT NULL DEFAULT '[]',
    evidence_level TEXT NOT NULL
        CHECK (evidence_level IN (
            'internal_evidence', 'profile_conflict',
            'model_judgment', 'insufficient'
        )),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    improvement_outline_json TEXT NOT NULL DEFAULT '[]',
    suggested_answer TEXT NOT NULL DEFAULT '',
    source_excerpt TEXT NOT NULL DEFAULT '',
    source_excerpt_sha256 TEXT,
    source_available INTEGER NOT NULL DEFAULT 1
        CHECK (source_available IN (0, 1)),
    result_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (result_status IN ('draft', 'formal', 'superseded')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(analysis_run_id, question_unit_id)
);
CREATE INDEX idx_interview_question_analyses_question
    ON interview_question_analyses(question_unit_id, created_at DESC, id);

CREATE TABLE interview_gaps (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL
        REFERENCES interview_analysis_runs(id) ON DELETE CASCADE,
    question_analysis_id TEXT NOT NULL
        REFERENCES interview_question_analyses(id) ON DELETE CASCADE,
    question_unit_id TEXT NOT NULL
        REFERENCES interview_question_units(id) ON DELETE CASCADE,
    gap_kind TEXT NOT NULL
        CHECK (gap_kind IN ('material', 'expression', 'knowledge', 'experience')),
    summary TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'resolved', 'dismissed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_interview_gaps_run_kind
    ON interview_gaps(analysis_run_id, gap_kind, status, id);

CREATE TABLE interview_asset_candidates (
    id TEXT PRIMARY KEY,
    retrospective_id TEXT NOT NULL
        REFERENCES interview_retrospectives(id) ON DELETE CASCADE,
    analysis_run_id TEXT NOT NULL
        REFERENCES interview_analysis_runs(id) ON DELETE CASCADE,
    question_unit_id TEXT
        REFERENCES interview_question_units(id) ON DELETE CASCADE,
    candidate_kind TEXT NOT NULL
        CHECK (candidate_kind IN (
            'review_question', 'profile_claim', 'project_narrative', 'summary'
        )),
    fingerprint TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    match_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'confirmed', 'rejected',
            'blocked', 'failed', 'superseded'
        )),
    target_resource_type TEXT,
    target_resource_id TEXT,
    last_error_code TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(retrospective_id, candidate_kind, fingerprint)
);
CREATE INDEX idx_interview_candidates_status
    ON interview_asset_candidates(
        retrospective_id, status, candidate_kind, updated_at DESC, id
    );

CREATE TABLE interview_action_items (
    id TEXT PRIMARY KEY,
    retrospective_id TEXT NOT NULL
        REFERENCES interview_retrospectives(id) ON DELETE CASCADE,
    analysis_run_id TEXT NOT NULL
        REFERENCES interview_analysis_runs(id) ON DELETE CASCADE,
    question_unit_id TEXT
        REFERENCES interview_question_units(id) ON DELETE SET NULL,
    gap_id TEXT REFERENCES interview_gaps(id) ON DELETE SET NULL,
    action_kind TEXT NOT NULL
        CHECK (action_kind IN ('material', 'expression', 'knowledge', 'experience')),
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'dismissed')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_interview_actions_status
    ON interview_action_items(
        retrospective_id, status, action_kind, updated_at DESC, id
    );

CREATE TABLE interview_write_receipts (
    id TEXT PRIMARY KEY,
    retrospective_id TEXT NOT NULL
        REFERENCES interview_retrospectives(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(retrospective_id, scope, idempotency_key)
);
CREATE INDEX idx_interview_receipts_scope
    ON interview_write_receipts(retrospective_id, scope, created_at DESC, id);
