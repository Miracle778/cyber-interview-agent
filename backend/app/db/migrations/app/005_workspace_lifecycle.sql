ALTER TABLE workspaces
    ADD COLUMN display_name TEXT NOT NULL DEFAULT '';

ALTER TABLE workspaces
    ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'active'
    CHECK (lifecycle_status IN ('active', 'recycled'));

ALTER TABLE workspaces
    ADD COLUMN recycled_at TEXT;

CREATE TABLE workspace_preferences (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    current_workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO workspace_preferences (singleton_id, current_workspace_id)
SELECT 1, id
FROM workspaces
ORDER BY updated_at DESC, rowid DESC
LIMIT 1;

INSERT OR IGNORE INTO workspace_preferences (singleton_id, current_workspace_id)
VALUES (1, NULL);

CREATE INDEX workspaces_lifecycle_updated_idx
    ON workspaces(lifecycle_status, updated_at DESC, id);
