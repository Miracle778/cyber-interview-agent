ALTER TABLE agent_eval_dimension_results
    ADD COLUMN evidence_refs_json TEXT NOT NULL DEFAULT '[]';

CREATE INDEX idx_agent_eval_dimensions_applicability_rating
    ON agent_eval_dimension_results(
        eval_run_id,
        applicability,
        rating,
        severity
    );
