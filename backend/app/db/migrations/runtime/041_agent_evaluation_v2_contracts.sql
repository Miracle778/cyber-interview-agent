ALTER TABLE agent_eval_runs
    ADD COLUMN evaluation_contract_version INTEGER NOT NULL DEFAULT 1
        CHECK (evaluation_contract_version > 0);

ALTER TABLE agent_eval_runs
    ADD COLUMN task_type TEXT NOT NULL DEFAULT 'legacy';

ALTER TABLE agent_eval_runs
    ADD COLUMN run_kind TEXT NOT NULL DEFAULT 'historical_review'
        CHECK (run_kind IN ('historical_review', 'agent_regression'));

ALTER TABLE agent_eval_runs
    ADD COLUMN business_outcome_hash TEXT
        CHECK (
            business_outcome_hash IS NULL
            OR length(business_outcome_hash) = 64
        );

ALTER TABLE agent_eval_runs
    ADD COLUMN judge_data_scope_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE agent_eval_dimension_results
    ADD COLUMN applicability TEXT NOT NULL DEFAULT 'applicable'
        CHECK (
            applicability IN (
                'applicable', 'not_applicable', 'insufficient_evidence'
            )
        );

ALTER TABLE agent_eval_dimension_results
    ADD COLUMN rating TEXT
        CHECK (
            rating IS NULL
            OR rating IN ('meets', 'usable', 'needs_review', 'severe')
        );

ALTER TABLE agent_eval_dimension_results
    ADD COLUMN severity TEXT
        CHECK (
            severity IS NULL
            OR severity IN ('none', 'low', 'medium', 'high', 'critical')
        );

ALTER TABLE agent_eval_dimension_results
    ADD COLUMN evidence_gaps_json TEXT NOT NULL DEFAULT '[]';

CREATE INDEX idx_agent_eval_runs_workspace_kind_created
    ON agent_eval_runs(workspace_id, run_kind, created_at DESC, id DESC);
