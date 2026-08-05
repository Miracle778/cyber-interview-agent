ALTER TABLE agent_quality_eval_settings
ADD COLUMN capture_regression_inputs INTEGER NOT NULL DEFAULT 0
    CHECK (capture_regression_inputs IN (0, 1));
