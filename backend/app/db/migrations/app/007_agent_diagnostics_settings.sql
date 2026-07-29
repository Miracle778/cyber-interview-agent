CREATE TABLE agent_diagnostics_settings (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    advanced_enabled INTEGER NOT NULL DEFAULT 0
        CHECK (advanced_enabled IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO agent_diagnostics_settings(singleton, advanced_enabled)
VALUES (1, 0);
