CREATE TABLE knowledge_sources (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    draft_id TEXT REFERENCES knowledge_drafts(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, stored_path)
);

CREATE INDEX idx_knowledge_sources_workspace_created
    ON knowledge_sources(workspace_id, created_at DESC, id DESC);
