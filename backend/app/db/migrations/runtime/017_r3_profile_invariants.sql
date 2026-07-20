-- Harden the first R3 persistence slice after repository review.

CREATE UNIQUE INDEX uq_profile_materials_active_role
    ON profile_materials(workspace_id, primary_role)
    WHERE lifecycle_status = 'active';

CREATE TABLE profile_idempotency_receipts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, operation, idempotency_key)
);

CREATE INDEX idx_profile_idempotency_receipts_workspace_created
    ON profile_idempotency_receipts(workspace_id, created_at DESC, id);
