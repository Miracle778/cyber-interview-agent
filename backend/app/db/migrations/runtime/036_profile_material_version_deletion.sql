ALTER TABLE profile_material_versions ADD COLUMN deleted_at TEXT;

CREATE INDEX idx_profile_material_versions_material_live
    ON profile_material_versions(material_id, deleted_at, version_number DESC, id);

ALTER TABLE profile_deletion_plans
    ADD COLUMN target_kind TEXT NOT NULL DEFAULT 'material' CHECK (
        target_kind IN ('material', 'material_version')
    );

ALTER TABLE profile_deletion_plans ADD COLUMN target_version_id TEXT;

CREATE INDEX idx_profile_deletion_plans_version
    ON profile_deletion_plans(
        workspace_id, target_kind, target_version_id, created_at DESC, id
    );
