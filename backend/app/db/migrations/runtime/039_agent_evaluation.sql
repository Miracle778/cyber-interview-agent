CREATE TABLE agent_eval_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    eval_pack_id TEXT NOT NULL,
    eval_pack_version INTEGER NOT NULL CHECK (eval_pack_version > 0),
    trigger TEXT NOT NULL CHECK (
        trigger IN ('manual', 'automatic', 'regression')
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending', 'running', 'completed', 'failed',
            'inconclusive', 'cancelled'
        )
    ),
    frozen_input_hash TEXT NOT NULL CHECK (length(frozen_input_hash) = 64),
    snapshot_json TEXT NOT NULL,
    deterministic_result_json TEXT,
    judge_provider_model_id TEXT,
    judge_trace_run_id TEXT,
    judge_result_json TEXT,
    error_code TEXT,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(workspace_id, idempotency_key)
);

CREATE INDEX idx_agent_eval_runs_workspace_created
    ON agent_eval_runs(workspace_id, created_at DESC, id DESC);
CREATE INDEX idx_agent_eval_runs_execution_pack
    ON agent_eval_runs(workspace_id, execution_id, eval_pack_id, eval_pack_version);

CREATE TABLE agent_eval_dimension_results (
    eval_run_id TEXT NOT NULL REFERENCES agent_eval_runs(id) ON DELETE CASCADE,
    dimension_id TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('deterministic', 'judge')),
    status TEXT NOT NULL CHECK (
        status IN ('passed', 'failed', 'scored', 'inconclusive')
    ),
    score INTEGER CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
    confidence REAL CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    ),
    summary TEXT NOT NULL,
    cited_event_hashes_json TEXT NOT NULL DEFAULT '[]',
    cited_artifact_hashes_json TEXT NOT NULL DEFAULT '[]',
    risks_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(eval_run_id, dimension_id, source)
);

CREATE TABLE agent_eval_human_feedback (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    eval_run_id TEXT NOT NULL REFERENCES agent_eval_runs(id) ON DELETE CASCADE,
    feedback_version INTEGER NOT NULL CHECK (feedback_version > 0),
    verdict TEXT NOT NULL CHECK (
        verdict IN ('accurate', 'incorrect', 'uncertain')
    ),
    dimension_id TEXT,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(eval_run_id, feedback_version)
);

CREATE INDEX idx_agent_eval_feedback_workspace_run
    ON agent_eval_human_feedback(workspace_id, eval_run_id, feedback_version);

CREATE TABLE agent_eval_regression_cases (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    source_eval_run_id TEXT REFERENCES agent_eval_runs(id) ON DELETE SET NULL,
    execution_id TEXT NOT NULL,
    eval_pack_id TEXT NOT NULL,
    eval_pack_version INTEGER NOT NULL CHECK (eval_pack_version > 0),
    case_version INTEGER NOT NULL DEFAULT 1 CHECK (case_version > 0),
    supersedes_case_id TEXT REFERENCES agent_eval_regression_cases(id),
    snapshot_hash TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
    snapshot_json TEXT NOT NULL,
    expected_invariants_json TEXT NOT NULL,
    contains_private_bodies INTEGER NOT NULL DEFAULT 0
        CHECK (contains_private_bodies IN (0, 1)),
    redaction_summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_agent_eval_cases_workspace_created
    ON agent_eval_regression_cases(workspace_id, created_at DESC, id DESC);

CREATE TABLE agent_eval_daily_counters (
    workspace_id TEXT NOT NULL,
    counter_date TEXT NOT NULL,
    automatic_count INTEGER NOT NULL DEFAULT 0 CHECK (automatic_count >= 0),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(workspace_id, counter_date)
);
