CREATE TABLE providers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    api_format TEXT NOT NULL CHECK (
        api_format IN ('openai-compatible', 'anthropic-compatible')
    ),
    base_url TEXT NOT NULL,
    secret_source TEXT NOT NULL,
    secret_ref TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE provider_models (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    connectivity_status TEXT NOT NULL DEFAULT 'unknown' CHECK (
        connectivity_status IN (
            'unknown',
            'ok',
            'secret_missing',
            'auth_failed',
            'model_not_found',
            'rate_limited',
            'timeout',
            'network_error',
            'protocol_error'
        )
    ),
    last_tested_at TEXT,
    last_error_code TEXT,
    last_latency_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider_id, model_id)
);

CREATE TABLE workspaces (
    id TEXT PRIMARY KEY,
    root_path TEXT NOT NULL UNIQUE,
    available INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE workspace_model_bindings (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (
        role IN (
            'question_generation',
            'answer_evaluation',
            'report_summarization',
            'agent_chat'
        )
    ),
    provider_model_id TEXT NOT NULL REFERENCES provider_models(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, role)
);

CREATE TABLE provider_test_runs (
    id TEXT PRIMARY KEY,
    provider_model_id TEXT NOT NULL REFERENCES provider_models(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    latency_ms INTEGER,
    error_code TEXT,
    message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
