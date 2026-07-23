ALTER TABLE profile_materials ADD COLUMN deleted_at TEXT;

CREATE INDEX idx_profile_materials_workspace_deleted
    ON profile_materials(workspace_id, deleted_at, lifecycle_status, updated_at DESC, id);

CREATE TABLE profile_deletion_plans (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    material_id TEXT NOT NULL,
    material_version INTEGER NOT NULL CHECK (material_version > 0),
    status TEXT NOT NULL DEFAULT 'planned' CHECK (
        status IN ('planned', 'executing', 'completed', 'failed', 'cancelled', 'expired')
    ),
    impact_json TEXT NOT NULL CHECK (
        json_valid(impact_json) AND json_type(impact_json) = 'object'
    ),
    result_json TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(result_json) AND json_type(result_json) = 'object'
    ),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE INDEX idx_profile_deletion_plans_material
    ON profile_deletion_plans(workspace_id, material_id, created_at DESC, id);
