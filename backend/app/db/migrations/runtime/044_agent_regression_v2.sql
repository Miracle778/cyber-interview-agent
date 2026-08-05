ALTER TABLE agent_eval_regression_cases
    ADD COLUMN case_contract_version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE agent_eval_regression_cases
    ADD COLUMN task_type TEXT NOT NULL DEFAULT 'legacy';

ALTER TABLE agent_eval_regression_cases
    ADD COLUMN sanitized_input_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE agent_eval_regression_cases
    ADD COLUMN required_domain_snapshot_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE agent_eval_regression_cases
    ADD COLUMN privacy_manifest_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE agent_eval_regression_cases
    ADD COLUMN baseline_versions_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE agent_eval_regression_cases
    ADD COLUMN source_business_outcome_json TEXT;

CREATE TABLE agent_eval_regression_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    case_id TEXT NOT NULL REFERENCES agent_eval_regression_cases(id) ON DELETE CASCADE,
    case_version INTEGER NOT NULL CHECK (case_version > 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'cancelled')
    ),
    baseline_implementation_id TEXT NOT NULL,
    candidate_implementation_id TEXT NOT NULL,
    baseline_execution_id TEXT,
    candidate_execution_id TEXT,
    baseline_outcome_hash TEXT,
    candidate_outcome_hash TEXT,
    deterministic_comparison_json TEXT,
    pairwise_result_json TEXT,
    infrastructure_failures_json TEXT NOT NULL DEFAULT '[]',
    isolation_manifest_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(workspace_id, idempotency_key)
);

CREATE INDEX idx_agent_eval_regression_runs_workspace_created
    ON agent_eval_regression_runs(workspace_id, created_at DESC, id DESC);
