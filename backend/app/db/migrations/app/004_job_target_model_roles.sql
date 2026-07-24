-- Add dedicated model roles for job analysis and project deep dives.

CREATE TABLE workspace_model_bindings_job_targets (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (
        role IN (
            'question_generation',
            'answer_evaluation',
            'report_summarization',
            'agent_chat',
            'profile_extraction',
            'profile_assessment',
            'job_analysis',
            'project_deep_dive'
        )
    ),
    provider_model_id TEXT NOT NULL REFERENCES provider_models(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, role)
);

INSERT INTO workspace_model_bindings_job_targets (
    workspace_id, role, provider_model_id, created_at, updated_at
)
SELECT workspace_id, role, provider_model_id, created_at, updated_at
FROM workspace_model_bindings;

INSERT INTO workspace_model_bindings_job_targets (
    workspace_id, role, provider_model_id
)
SELECT workspace_id, 'job_analysis', provider_model_id
FROM workspace_model_bindings
WHERE role = 'profile_assessment';

INSERT INTO workspace_model_bindings_job_targets (
    workspace_id, role, provider_model_id
)
SELECT workspace_id, 'project_deep_dive', provider_model_id
FROM workspace_model_bindings
WHERE role = 'agent_chat';

DROP TABLE workspace_model_bindings;
ALTER TABLE workspace_model_bindings_job_targets
    RENAME TO workspace_model_bindings;
