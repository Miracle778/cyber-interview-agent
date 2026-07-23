CREATE TABLE profile_agent_context (
    session_id TEXT PRIMARY KEY
        REFERENCES agent_sessions(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    material_id TEXT,
    material_version_id TEXT,
    claim_id TEXT,
    proposal_id TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX profile_agent_context_workspace_idx
    ON profile_agent_context(workspace_id, updated_at DESC);

CREATE UNIQUE INDEX profile_action_plans_execution_unique
    ON profile_action_plans(execution_id)
    WHERE execution_id IS NOT NULL;
