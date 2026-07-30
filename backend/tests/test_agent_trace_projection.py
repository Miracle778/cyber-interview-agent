from __future__ import annotations

import json

from app.observability.projection import TraceMetadataProjector
from test_agent_trace_retention import _service


class CapturingExporter:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.payloads: list[dict[str, object]] = []
        self.fail_once = fail_once

    def export(self, payload: dict[str, object]) -> None:
        self.payloads.append(payload)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("private exporter response")


def test_projection_exports_only_allowlisted_hashed_metadata(tmp_path) -> None:
    connection, _retention = _service(tmp_path)
    exporter = CapturingExporter()
    try:
        connection.execute(
            "UPDATE agent_runs SET input_json = ? WHERE id = 'run-1'",
            (json.dumps({"resume": "PRIVATE RESUME", "api_key": "SECRET"}),),
        )
        connection.commit()
        projector = TraceMetadataProjector(
            connection=connection,
            workspace_id="workspace-1",
            exporter=exporter,
        )
        first = projector.project_execution("run-1")
        replay = projector.project_execution("run-1")
        encoded = json.dumps(exporter.payloads, ensure_ascii=False)
        assert first.delivered >= 1
        assert replay.skipped == first.delivered
        assert "PRIVATE RESUME" not in encoded
        assert "SECRET" not in encoded
        assert str(tmp_path) not in encoded
        assert "workspace-1" not in encoded
        assert all("workspaceIdHash" in payload for payload in exporter.payloads)
        assert all("prompt" not in str(payload).casefold() for payload in exporter.payloads)
    finally:
        connection.close()


def test_projection_failure_is_recorded_and_retry_succeeds(tmp_path) -> None:
    connection, _retention = _service(tmp_path)
    exporter = CapturingExporter(fail_once=True)
    try:
        projector = TraceMetadataProjector(
            connection=connection,
            workspace_id="workspace-1",
            exporter=exporter,
        )
        failed = projector.project_execution("run-1")
        retried = projector.project_execution("run-1")
        assert failed.failed == 1
        assert retried.delivered == 1
        statuses = {
            row[0]
            for row in connection.execute(
                "SELECT status FROM agent_trace_projection_deliveries"
            )
        }
        assert statuses == {"completed"}
        assert connection.execute(
            "SELECT status FROM agent_runs WHERE id = 'run-1'"
        ).fetchone()[0] == "completed"
    finally:
        connection.close()
