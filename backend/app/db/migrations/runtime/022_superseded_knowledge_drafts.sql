CREATE TABLE knowledge_drafts_v22 (
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
        status IN (
            'draft', 'review_pending', 'rejected', 'published', 'superseded'
        )
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, content_path)
);

INSERT INTO knowledge_drafts_v22 (
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
ALTER TABLE knowledge_drafts_v22 RENAME TO knowledge_drafts;

CREATE INDEX idx_knowledge_drafts_workspace_status_updated
    ON knowledge_drafts(workspace_id, status, updated_at DESC, id);
