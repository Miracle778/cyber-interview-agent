-- R3 adds profile_extraction and profile_assessment model roles. Rebuild
-- workspace_model_bindings so its role CHECK accepts all six roles; existing
-- four-role bindings are preserved unchanged.

CREATE TABLE workspace_model_bindings_r3 (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (
        role IN (
            'question_generation',
            'answer_evaluation',
            'report_summarization',
            'agent_chat',
            'profile_extraction',
            'profile_assessment'
        )
    ),
    provider_model_id TEXT NOT NULL REFERENCES provider_models(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, role)
);

INSERT INTO workspace_model_bindings_r3 (
    workspace_id, role, provider_model_id, created_at, updated_at
)
SELECT
    workspace_id, role, provider_model_id, created_at, updated_at
FROM workspace_model_bindings;

DROP TABLE workspace_model_bindings;
ALTER TABLE workspace_model_bindings_r3 RENAME TO workspace_model_bindings;
