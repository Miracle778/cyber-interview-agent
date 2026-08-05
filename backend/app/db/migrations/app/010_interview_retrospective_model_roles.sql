-- Add dedicated model roles for interview retrospective analysis and chat.

CREATE TABLE workspace_model_bindings_retrospectives (
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
            'project_deep_dive',
            'retrospective_analysis',
            'retrospective_chat'
        )
    ),
    provider_model_id TEXT NOT NULL
        REFERENCES provider_models(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, role)
);

INSERT INTO workspace_model_bindings_retrospectives (
    workspace_id, role, provider_model_id, created_at, updated_at
)
SELECT workspace_id, role, provider_model_id, created_at, updated_at
FROM workspace_model_bindings;

INSERT INTO workspace_model_bindings_retrospectives (
    workspace_id, role, provider_model_id
)
SELECT workspace_id, 'retrospective_analysis', provider_model_id
FROM workspace_model_bindings
WHERE role = 'job_analysis';

INSERT INTO workspace_model_bindings_retrospectives (
    workspace_id, role, provider_model_id
)
SELECT workspace_id, 'retrospective_chat', provider_model_id
FROM workspace_model_bindings
WHERE role = 'project_deep_dive';

DROP TABLE workspace_model_bindings;
ALTER TABLE workspace_model_bindings_retrospectives
    RENAME TO workspace_model_bindings;
