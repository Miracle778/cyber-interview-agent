ALTER TABLE provider_models
ADD COLUMN max_input_tokens INTEGER NOT NULL DEFAULT 128000
CHECK (max_input_tokens >= 4096 AND max_input_tokens <= 2000000);
