CREATE TABLE agent_quality_eval_settings (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    automatic_sample_percent INTEGER NOT NULL DEFAULT 5
        CHECK (automatic_sample_percent >= 0 AND automatic_sample_percent <= 100),
    automatic_daily_cap INTEGER NOT NULL DEFAULT 20
        CHECK (automatic_daily_cap >= 0 AND automatic_daily_cap <= 1000),
    judge_provider_model_id TEXT REFERENCES provider_models(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO agent_quality_eval_settings(
    singleton,
    enabled,
    automatic_sample_percent,
    automatic_daily_cap,
    judge_provider_model_id
) VALUES (1, 0, 5, 20, NULL);
