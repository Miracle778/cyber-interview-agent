ALTER TABLE provider_models
ADD COLUMN resolved_model_id TEXT;

ALTER TABLE provider_models
ADD COLUMN capability_profile_json TEXT NOT NULL DEFAULT '{}'
CHECK (json_valid(capability_profile_json));

ALTER TABLE provider_models
ADD COLUMN capabilities_tested_at TEXT;
