-- R3 personal profile agent: material/version/evidence/claim/proposal/plan/publication
-- domain tables, plus the shared Runtime changes they depend on.
--
-- Shared Runtime changes:
--   * agent_sessions.visibility separates user-visible sessions from hidden
--     profile.ingest system sessions (session_id == material_version_id).
--   * tool_audits gains tool_call_id/agent_role/input_digest/result_digest and a
--     'denied' status so the Tool policy middleware can correlate and audit
--     denied calls without persisting raw arguments or results.
--   * agent_messages.message_kind accepts typed profile cards and receipts.
--   * knowledge_drafts.document_type accepts 'profile'; publication_runs.state
--     accepts 'revoked' for recoverable revocation.
--
-- R3 domain facts live here; LangGraph checkpoints keep orchestration state only.

ALTER TABLE agent_sessions
    ADD COLUMN visibility TEXT NOT NULL DEFAULT 'user' CHECK (
        visibility IN ('user', 'system')
    );

CREATE INDEX idx_agent_sessions_workspace_visibility_updated
    ON agent_sessions(workspace_id, visibility, updated_at DESC, id);

-- Rebuild agent_messages so message_kind accepts the R3 typed card kinds.
CREATE TABLE agent_messages_r3 (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    message_kind TEXT NOT NULL DEFAULT 'text' CHECK (
        message_kind IN (
            'text', 'stage', 'curation_summary', 'question_card',
            'review_prompt', 'review_answer', 'evaluation_card',
            'command_receipt', 'error',
            'claim_card', 'proposal_card', 'assessment_card',
            'action_plan_card', 'receipt'
        )
    ),
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(payload_json) AND json_type(payload_json) = 'object'
    )
);

INSERT INTO agent_messages_r3 (
    id, session_id, run_id, role, content, created_at, message_kind, payload_json
)
SELECT
    id, session_id, run_id, role, content, created_at, message_kind, payload_json
FROM agent_messages;

DROP TABLE agent_messages;
ALTER TABLE agent_messages_r3 RENAME TO agent_messages;

CREATE INDEX idx_agent_messages_session_created
    ON agent_messages(session_id, created_at, id);

-- Rebuild tool_audits with correlation/digest columns and the 'denied' status.
CREATE TABLE tool_audits_r3 (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('started', 'completed', 'failed', 'denied')
    ),
    tool_call_id TEXT,
    agent_role TEXT,
    input_digest TEXT,
    result_digest TEXT,
    error_code TEXT,
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    resource_scope TEXT,
    resource_path TEXT,
    resource_sha256 TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

INSERT INTO tool_audits_r3 (
    id, session_id, run_id, tool_name, status, error_code, latency_ms,
    resource_scope, resource_path, resource_sha256, created_at, finished_at
)
SELECT
    id, session_id, run_id, tool_name, status, error_code, latency_ms,
    resource_scope, resource_path, resource_sha256, created_at, finished_at
FROM tool_audits;

DROP TABLE tool_audits;
ALTER TABLE tool_audits_r3 RENAME TO tool_audits;

CREATE INDEX idx_tool_audits_run_created ON tool_audits(run_id, created_at, id);
CREATE INDEX idx_tool_audits_call ON tool_audits(tool_call_id, id);

-- Rebuild knowledge_drafts so document_type accepts the 'profile' document.
CREATE TABLE knowledge_drafts_r3 (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    agent_type TEXT,
    domain TEXT NOT NULL,
    document_type TEXT NOT NULL CHECK (
        document_type IN (
            'source', 'question', 'concept',
            'session_report', 'mastery_report', 'profile'
        )
    ),
    document_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content_path TEXT NOT NULL,
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    relation_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (
        status IN ('draft', 'review_pending', 'rejected', 'published')
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, content_path)
);

INSERT INTO knowledge_drafts_r3 (
    id, workspace_id, session_id, run_id, agent_type, domain, document_type,
    document_id, title, content_path, source_refs_json, relation_refs_json,
    status, version, content_hash, created_at, updated_at
)
SELECT
    id, workspace_id, session_id, run_id, agent_type, domain, document_type,
    document_id, title, content_path, source_refs_json, relation_refs_json,
    status, version, content_hash, created_at, updated_at
FROM knowledge_drafts;

DROP TABLE knowledge_drafts;
ALTER TABLE knowledge_drafts_r3 RENAME TO knowledge_drafts;

CREATE INDEX idx_knowledge_drafts_workspace_status_updated
    ON knowledge_drafts(workspace_id, status, updated_at DESC, id);

-- Rebuild publication_runs so state accepts 'revoked' for recoverable revocation.
CREATE TABLE publication_runs_r3 (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE REFERENCES pending_actions(id) ON DELETE RESTRICT,
    draft_id TEXT NOT NULL REFERENCES knowledge_drafts(id) ON DELETE RESTRICT,
    expected_draft_version INTEGER NOT NULL CHECK (expected_draft_version > 0),
    expected_content_hash TEXT NOT NULL,
    document_id TEXT NOT NULL,
    target_path TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'prepared' CHECK (
        state IN (
            'prepared', 'file_written', 'indexed', 'completed',
            'index_stale', 'failed', 'revoked'
        )
    ),
    result_hash TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

INSERT INTO publication_runs_r3 (
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
ALTER TABLE publication_runs_r3 RENAME TO publication_runs;

CREATE INDEX idx_publication_runs_state_updated
    ON publication_runs(state, updated_at, id);

-- R3 domain tables.

CREATE TABLE profile_materials (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK (
        type IN ('resume', 'github', 'blog', 'research', 'project_document')
    ),
    title TEXT NOT NULL,
    primary_role TEXT NOT NULL,
    current_version_id TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active' CHECK (
        lifecycle_status IN ('active', 'archived')
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_profile_materials_workspace_role_status
    ON profile_materials(workspace_id, primary_role, lifecycle_status, updated_at DESC, id);

CREATE TABLE profile_material_versions (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL REFERENCES profile_materials(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    source_type TEXT NOT NULL CHECK (source_type IN ('upload', 'derived_draft')),
    file_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    storage_ref TEXT NOT NULL,
    text_ref TEXT NOT NULL,
    processing_status TEXT NOT NULL DEFAULT 'uploaded' CHECK (
        processing_status IN (
            'uploaded', 'parsing', 'parsed', 'extracting',
            'ready', 'parse_failed', 'extraction_failed'
        )
    ),
    derived_from_version_id TEXT REFERENCES profile_material_versions(id) ON DELETE SET NULL,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(material_id, version_number)
);

CREATE INDEX idx_profile_material_versions_material
    ON profile_material_versions(material_id, version_number DESC, id);

CREATE TABLE profile_evidence (
    id TEXT PRIMARY KEY,
    material_version_id TEXT NOT NULL REFERENCES profile_material_versions(id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset >= 0),
    sanitized_text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'normal' CHECK (
        sensitivity IN ('normal', 'sensitive')
    ),
    tombstoned_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (end_offset >= start_offset)
);

CREATE INDEX idx_profile_evidence_version
    ON profile_evidence(material_version_id, id);

CREATE TABLE profile_claims (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    claim_type TEXT NOT NULL CHECK (
        claim_type IN ('skill', 'project', 'experience', 'education', 'link')
    ),
    current_confirmed_version_id TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_profile_claims_workspace_type
    ON profile_claims(workspace_id, claim_type, updated_at DESC, id);

CREATE TABLE profile_claim_versions (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES profile_claims(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    value_json TEXT NOT NULL CHECK (
        json_valid(value_json) AND json_type(value_json) = 'object'
    ),
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (
        status IN ('proposed', 'confirmed', 'rejected', 'superseded')
    ),
    support_status TEXT NOT NULL DEFAULT 'unsupported' CHECK (
        support_status IN ('supported', 'conflicted', 'unsupported')
    ),
    evidence_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (
        json_valid(evidence_ids_json) AND json_type(evidence_ids_json) = 'array'
    ),
    source TEXT NOT NULL,
    expected_previous_version INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TEXT,
    UNIQUE(claim_id, version)
);

CREATE INDEX idx_profile_claim_versions_claim
    ON profile_claim_versions(claim_id, version DESC, id);

CREATE TABLE profile_claim_proposals (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    proposal_type TEXT NOT NULL CHECK (
        proposal_type IN ('create', 'update', 'reject')
    ),
    target_claim_id TEXT REFERENCES profile_claims(id) ON DELETE SET NULL,
    base_claim_version_id TEXT REFERENCES profile_claim_versions(id) ON DELETE SET NULL,
    proposed_value_json TEXT NOT NULL CHECK (
        json_valid(proposed_value_json) AND json_type(proposed_value_json) = 'object'
    ),
    reason TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (
        json_valid(evidence_ids_json) AND json_type(evidence_ids_json) = 'array'
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'accepted', 'rejected', 'superseded')
    ),
    created_by_execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    decided_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_profile_claim_proposals_workspace_status
    ON profile_claim_proposals(workspace_id, status, created_at DESC, id);
CREATE INDEX idx_profile_claim_proposals_target
    ON profile_claim_proposals(target_claim_id, status, id);

CREATE TABLE profile_claim_conflicts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    claim_id TEXT NOT NULL REFERENCES profile_claims(id) ON DELETE CASCADE,
    proposal_id TEXT NOT NULL REFERENCES profile_claim_proposals(id) ON DELETE CASCADE,
    conflicting_claim_version_id TEXT NOT NULL REFERENCES profile_claim_versions(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(claim_id, proposal_id, conflicting_claim_version_id)
);

CREATE INDEX idx_profile_claim_conflicts_claim
    ON profile_claim_conflicts(claim_id, id);

CREATE TABLE profile_assessments (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    base_profile_version TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK (
        json_valid(result_json) AND json_type(result_json) = 'object'
    ),
    created_by_execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_profile_assessments_workspace
    ON profile_assessments(workspace_id, created_at DESC, id);

CREATE TABLE profile_action_plans (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    request_summary TEXT NOT NULL,
    base_profile_version TEXT NOT NULL,
    selection_snapshot_json TEXT NOT NULL CHECK (
        json_valid(selection_snapshot_json) AND json_type(selection_snapshot_json) = 'object'
    ),
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (
        status IN (
            'proposed', 'validated', 'awaiting_confirmation', 'executing',
            'completed', 'partially_completed', 'failed', 'cancelled', 'expired'
        )
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TEXT,
    completed_at TEXT
);

CREATE INDEX idx_profile_action_plans_session
    ON profile_action_plans(session_id, created_at DESC, id);
CREATE INDEX idx_profile_action_plans_workspace_status
    ON profile_action_plans(workspace_id, status, created_at DESC, id);

CREATE TABLE profile_action_plan_items (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES profile_action_plans(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    operation TEXT NOT NULL,
    target_json TEXT NOT NULL CHECK (
        json_valid(target_json) AND json_type(target_json) = 'object'
    ),
    expected_version INTEGER,
    before_json TEXT,
    after_json TEXT NOT NULL CHECK (
        json_valid(after_json) AND json_type(after_json) = 'object'
    ),
    evidence_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (
        json_valid(evidence_ids_json) AND json_type(evidence_ids_json) = 'array'
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'completed', 'failed', 'skipped')
    ),
    receipt_id TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(plan_id, item_id)
);

CREATE INDEX idx_profile_action_plan_items_plan
    ON profile_action_plan_items(plan_id, ordinal, id);

CREATE TABLE profile_publication_selections (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    excluded_sensitive_fields_json TEXT NOT NULL DEFAULT '[]' CHECK (
        json_valid(excluded_sensitive_fields_json)
        AND json_type(excluded_sensitive_fields_json) = 'array'
    ),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (
        status IN ('draft', 'submitted', 'superseded')
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_profile_publication_selections_workspace
    ON profile_publication_selections(workspace_id, status, updated_at DESC, id);

CREATE TABLE profile_publication_selection_items (
    selection_id TEXT NOT NULL REFERENCES profile_publication_selections(id) ON DELETE CASCADE,
    claim_version_id TEXT NOT NULL REFERENCES profile_claim_versions(id) ON DELETE CASCADE,
    PRIMARY KEY (selection_id, claim_version_id)
);

CREATE INDEX idx_profile_publication_selection_items_selection
    ON profile_publication_selection_items(selection_id, claim_version_id);

CREATE TABLE profile_publications (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    draft_id TEXT REFERENCES knowledge_drafts(id) ON DELETE SET NULL,
    publication_run_id TEXT REFERENCES publication_runs(id) ON DELETE SET NULL,
    selection_id TEXT REFERENCES profile_publication_selections(id) ON DELETE SET NULL,
    profile_version TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (
        state IN ('pending', 'published', 'revoked', 'failed')
    ),
    published_hash TEXT,
    revoked_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_profile_publications_workspace_state
    ON profile_publications(workspace_id, state, updated_at DESC, id);
CREATE INDEX idx_profile_publications_draft
    ON profile_publications(draft_id, id);
