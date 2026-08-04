ALTER TABLE agent_runs
ADD COLUMN agent_definition_snapshot_json TEXT NOT NULL
DEFAULT '{"snapshot_version":1,"legacy":true}';

CREATE TRIGGER agent_runs_definition_snapshot_immutable
BEFORE UPDATE OF agent_definition_snapshot_json ON agent_runs
WHEN NEW.agent_definition_snapshot_json <> OLD.agent_definition_snapshot_json
BEGIN
    SELECT RAISE(ABORT, 'agent_definition_snapshot_immutable');
END;
