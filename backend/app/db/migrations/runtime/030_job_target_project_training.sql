-- Job target preparation, recoverable analysis, project deep dives, and
-- one-message-to-many-execution attempts.

ALTER TABLE agent_runs ADD COLUMN input_message_id TEXT
    REFERENCES agent_messages(id) ON DELETE SET NULL;
ALTER TABLE agent_runs ADD COLUMN retry_of_execution_id TEXT
    REFERENCES agent_runs(id) ON DELETE SET NULL;
CREATE INDEX idx_agent_runs_input_message
    ON agent_runs(input_message_id, created_at, id);

ALTER TABLE agent_messages ADD COLUMN replaces_message_id TEXT
    REFERENCES agent_messages(id) ON DELETE SET NULL;
ALTER TABLE agent_messages ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'active'
    CHECK (resolution_status IN ('active', 'unresolved', 'replaced', 'abandoned'));
CREATE INDEX idx_agent_messages_resolution
    ON agent_messages(session_id, resolution_status, created_at, id);

ALTER TABLE review_question_candidates
    ADD COLUMN question_type TEXT NOT NULL DEFAULT 'technical'
    CHECK (question_type IN ('technical', 'project_experience'));
ALTER TABLE review_question_candidates ADD COLUMN project_claim_id TEXT;
ALTER TABLE review_question_candidates ADD COLUMN project_dimension TEXT;
ALTER TABLE review_question_candidates ADD COLUMN source_job_target_id TEXT;
ALTER TABLE review_question_candidates ADD COLUMN source_deep_dive_id TEXT;

ALTER TABLE review_question_catalog
    ADD COLUMN question_type TEXT NOT NULL DEFAULT 'technical'
    CHECK (question_type IN ('technical', 'project_experience'));
ALTER TABLE review_question_catalog ADD COLUMN project_claim_id TEXT;
ALTER TABLE review_question_catalog ADD COLUMN project_dimension TEXT;
ALTER TABLE review_question_catalog ADD COLUMN source_job_target_id TEXT;
ALTER TABLE review_question_catalog ADD COLUMN source_deep_dive_id TEXT;
CREATE INDEX idx_review_catalog_project
    ON review_question_catalog(
        workspace_id, question_type, project_claim_id, active, updated_at DESC
    );

CREATE TABLE job_targets (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    company_name TEXT,
    role_name TEXT NOT NULL,
    seniority TEXT NOT NULL,
    source_url TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active'
        CHECK (lifecycle_status IN ('active', 'archived', 'recycled')),
    current_document_version_id TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_job_targets_workspace_lifecycle
    ON job_targets(workspace_id, lifecycle_status, updated_at DESC, id);

CREATE TABLE job_document_versions (
    id TEXT PRIMARY KEY,
    job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    source_kind TEXT NOT NULL
        CHECK (source_kind IN ('jd_text', 'direction_reference')),
    body TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_target_id, ordinal)
);
CREATE UNIQUE INDEX ux_job_document_current
    ON job_document_versions(job_target_id) WHERE is_current = 1;

CREATE TABLE job_requirements (
    id TEXT PRIMARY KEY,
    job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL
        REFERENCES job_document_versions(id) ON DELETE CASCADE,
    stable_key TEXT NOT NULL,
    requirement_type TEXT NOT NULL
        CHECK (requirement_type IN ('responsibility', 'skill', 'experience', 'project')),
    priority TEXT NOT NULL CHECK (priority IN ('must_have', 'nice_to_have')),
    text TEXT NOT NULL,
    source_quote TEXT NOT NULL,
    source_start INTEGER,
    source_end INTEGER,
    inferred INTEGER NOT NULL DEFAULT 0 CHECK (inferred IN (0, 1)),
    confirmation_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (confirmation_status IN ('pending', 'confirmed', 'rejected', 'superseded')),
    preparation_status TEXT NOT NULL DEFAULT 'needs_deep_dive'
        CHECK (preparation_status IN (
            'reliable_evidence', 'needs_deep_dive',
            'profile_incomplete', 'no_experience'
        )),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_version_id, stable_key)
);
CREATE INDEX idx_job_requirements_target_status
    ON job_requirements(job_target_id, confirmation_status, updated_at DESC, id);

CREATE TABLE job_requirement_evidence_links (
    id TEXT PRIMARY KEY,
    job_requirement_id TEXT NOT NULL REFERENCES job_requirements(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL
        CHECK (source_kind IN ('profile_claim', 'project', 'narrative', 'training')),
    source_id TEXT NOT NULL,
    source_version_id TEXT,
    status TEXT NOT NULL DEFAULT 'suggested'
        CHECK (status IN ('suggested', 'confirmed', 'rejected', 'stale')),
    rationale TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_requirement_id, source_kind, source_id, source_version_id)
);

CREATE TABLE job_analysis_runs (
    id TEXT PRIMARY KEY,
    job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL
        REFERENCES job_document_versions(id) ON DELETE CASCADE,
    execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    profile_version INTEGER NOT NULL,
    input_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN (
            'queued', 'running', 'pausing', 'paused', 'interrupted',
            'review_pending', 'completed', 'failed', 'terminated'
        )),
    stage TEXT NOT NULL DEFAULT 'reading_job'
        CHECK (stage IN (
            'reading_job', 'extracting_requirements', 'mapping_profile',
            'mapping_projects', 'finalizing', 'waiting_for_review',
            'completed', 'failed', 'terminated'
        )),
    control_intent TEXT CHECK (control_intent IN ('pause', 'terminate')),
    cumulative_elapsed_ms INTEGER NOT NULL DEFAULT 0 CHECK (cumulative_elapsed_ms >= 0),
    latest_progress_at TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX ux_job_analysis_active
    ON job_analysis_runs(job_target_id)
    WHERE status IN ('queued', 'running', 'pausing');

CREATE TABLE job_analysis_work_items (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL REFERENCES job_analysis_runs(id) ON DELETE CASCADE,
    work_key TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'retryable', 'interrupted', 'skipped')),
    output_json TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(analysis_run_id, work_key)
);
CREATE INDEX idx_job_analysis_items_status
    ON job_analysis_work_items(analysis_run_id, status, updated_at, id);

CREATE TABLE job_target_project_priorities (
    job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
    project_claim_id TEXT NOT NULL REFERENCES profile_claims(id) ON DELETE RESTRICT,
    priority_kind TEXT NOT NULL CHECK (priority_kind IN ('core', 'supplementary')),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    rationale TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(job_target_id, project_claim_id),
    UNIQUE(job_target_id, priority_kind, ordinal)
);

CREATE TABLE project_deep_dives (
    id TEXT PRIMARY KEY,
    job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
    project_claim_id TEXT NOT NULL REFERENCES profile_claims(id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL UNIQUE REFERENCES agent_sessions(id) ON DELETE CASCADE,
    current_stage TEXT NOT NULL DEFAULT 'background'
        CHECK (current_stage IN (
            'background', 'role', 'solution', 'difficulty',
            'outcome', 'tradeoff', 'target_follow_up', 'finished'
        )),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'interrupted', 'completed', 'terminated', 'archived')),
    current_question_id TEXT,
    completed_stage_ids_json TEXT NOT NULL DEFAULT '[]',
    follow_up_ids_json TEXT NOT NULL DEFAULT '[]',
    waiting_for_input INTEGER NOT NULL DEFAULT 0 CHECK (waiting_for_input IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX ux_project_deep_dive_primary
    ON project_deep_dives(job_target_id, project_claim_id)
    WHERE status != 'archived';

CREATE TABLE project_narrative_sections (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_claim_id TEXT NOT NULL REFERENCES profile_claims(id) ON DELETE RESTRICT,
    section_kind TEXT NOT NULL
        CHECK (section_kind IN (
            'background', 'role', 'solution', 'difficulty',
            'outcome', 'tradeoff', 'retrospective'
        )),
    content TEXT NOT NULL,
    source_session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    source_message_id TEXT REFERENCES agent_messages(id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    status TEXT NOT NULL DEFAULT 'confirmed'
        CHECK (status IN ('confirmed', 'superseded')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_claim_id, section_kind, version)
);
CREATE UNIQUE INDEX ux_project_narrative_current
    ON project_narrative_sections(project_claim_id, section_kind)
    WHERE status = 'confirmed';

CREATE TABLE project_deep_dive_artifacts (
    id TEXT PRIMARY KEY,
    deep_dive_id TEXT NOT NULL REFERENCES project_deep_dives(id) ON DELETE CASCADE,
    artifact_kind TEXT NOT NULL
        CHECK (artifact_kind IN ('turn_result', 'narrative_proposal', 'target_finding', 'question_batch')),
    source_execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    source_message_id TEXT REFERENCES agent_messages(id) ON DELETE SET NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'partially_confirmed', 'confirmed', 'rejected', 'superseded')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE project_gaps (
    id TEXT PRIMARY KEY,
    deep_dive_id TEXT NOT NULL REFERENCES project_deep_dives(id) ON DELETE CASCADE,
    gap_kind TEXT NOT NULL CHECK (gap_kind IN ('profile', 'expression', 'knowledge', 'experience')),
    summary TEXT NOT NULL,
    source_artifact_id TEXT REFERENCES project_deep_dive_artifacts(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'accepted_risk', 'resolved', 'dismissed')),
    resolution_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE project_question_candidates (
    id TEXT PRIMARY KEY,
    deep_dive_id TEXT NOT NULL REFERENCES project_deep_dives(id) ON DELETE CASCADE,
    project_claim_id TEXT NOT NULL REFERENCES profile_claims(id) ON DELETE RESTRICT,
    dimension TEXT NOT NULL
        CHECK (dimension IN (
            'background_role', 'architecture_solution',
            'difficulty_problem_solving', 'outcome',
            'tradeoff_failure_retrospective', 'target_specific'
        )),
    question_json TEXT NOT NULL,
    duplicate_of_question_id TEXT,
    review_candidate_id TEXT REFERENCES review_question_candidates(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'review_pending'
        CHECK (status IN ('review_pending', 'confirmed', 'ignored', 'duplicate')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE job_execution_context_manifests (
    execution_id TEXT PRIMARY KEY REFERENCES agent_runs(id) ON DELETE CASCADE,
    job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
    project_claim_id TEXT,
    context_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE job_target_idempotency_receipts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, operation, idempotency_key)
);
