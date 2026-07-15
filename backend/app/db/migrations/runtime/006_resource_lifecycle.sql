ALTER TABLE agent_sessions ADD COLUMN deleted_at TEXT;

CREATE INDEX idx_agent_sessions_workspace_visible
    ON agent_sessions(workspace_id, deleted_at, updated_at DESC);

ALTER TABLE knowledge_sources ADD COLUMN deleted_at TEXT;

CREATE INDEX idx_knowledge_sources_workspace_visible
    ON knowledge_sources(workspace_id, deleted_at, created_at DESC);
