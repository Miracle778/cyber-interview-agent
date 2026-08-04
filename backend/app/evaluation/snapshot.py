from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from app.evaluation.contracts import EvalPack
from app.agents.definition_snapshot import AgentDefinitionSnapshot
from app.observability.content_reader import (
    TraceContentNotFoundError,
    TraceContentUnavailableError,
)


@dataclass(frozen=True, slots=True)
class FrozenTraceEvent:
    event_id: str
    operation_id: str
    event_type: str
    observed_at: str | None
    payload_sha256: str
    sequence: int
    available: bool
    content: str | None


@dataclass(frozen=True, slots=True)
class FrozenArtifactReference:
    source: str
    sha256: str


@dataclass(frozen=True, slots=True)
class FrozenEvaluationSnapshot:
    snapshot_version: int
    workspace_id: str
    execution: dict[str, Any]
    eval_pack_id: str
    eval_pack_version: int
    events: tuple[FrozenTraceEvent, ...]
    artifacts: tuple[FrozenArtifactReference, ...]
    versions: dict[str, str]
    model_bindings: dict[str, str]
    tool_versions: dict[str, str]
    captured_at: str

    def canonical_json(self) -> str:
        payload = asdict(self)
        payload.pop("captured_at", None)
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def frozen_input_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class EvaluationSnapshotBuilder:
    def __init__(self, observability_service) -> None:
        self.service = observability_service

    def build(
        self, run_id: str, pack: EvalPack
    ) -> FrozenEvaluationSnapshot:
        row = self.service._run(run_id)
        input_payload = _parse_object(row.get("input_json"))
        model_bindings = _string_mapping(
            _parse_object(row.get("model_bindings_json"))
        )
        configuration = _parse_object(row.get("configuration_json"))
        raw_definition_snapshot = row.get("agent_definition_snapshot_json")
        definition_snapshot = AgentDefinitionSnapshot.from_json(
            raw_definition_snapshot
            if isinstance(raw_definition_snapshot, str)
            else AgentDefinitionSnapshot.legacy_snapshot().to_json()
        )
        tool_versions = _string_mapping(
            configuration.get("tool_versions")
            if isinstance(configuration, dict)
            else None
        )
        events = tuple(
            self._event(row)
            for row in self.service.trace_repository.list_events(run_id)
        )
        artifacts = tuple(
            FrozenArtifactReference(source=source, sha256=digest)
            for source, digest in sorted(_find_hashes(input_payload))
        )
        versions = {
            "graph": str(
                definition_snapshot.graph_version
                if not definition_snapshot.legacy
                else row.get("graph_version") or "unknown"
            ),
            "trace": "3",
            "snapshot": "1",
        }
        if not definition_snapshot.legacy:
            versions.update(
                {
                    "agentDefinition": str(
                        definition_snapshot.agent_definition_version
                    ),
                    "inputSchema": str(definition_snapshot.input_schema_version),
                    "outputSchema": str(definition_snapshot.output_schema_version),
                    "contextPolicy": str(definition_snapshot.context_policy_id),
                    "retryPolicy": str(definition_snapshot.retry_policy_id),
                    "tracePolicy": str(definition_snapshot.trace_policy_id),
                    "toolsetDigest": str(definition_snapshot.toolset_digest),
                    "modelBindingDigest": str(
                        definition_snapshot.model_binding_digest
                    ),
                }
            )
            for prompt_id, version in definition_snapshot.prompt_schema_versions:
                versions[f"prompt:{prompt_id}"] = version
        if isinstance(configuration, dict):
            if configuration.get("prompt_version") is not None:
                versions["prompt"] = str(configuration["prompt_version"])
            if configuration.get("schema_version") is not None:
                versions["schema"] = str(configuration["schema_version"])
        return FrozenEvaluationSnapshot(
            snapshot_version=1,
            workspace_id=self.service.workspace_id,
            execution={
                "id": row["id"],
                "sessionId": row["session_id"],
                "workspaceId": row["workspace_id"],
                "graphId": row["graph_id"],
                "graphVersion": (
                    definition_snapshot.graph_version
                    if not definition_snapshot.legacy
                    else row["graph_version"]
                ),
                "agentDefinitionSnapshot": definition_snapshot.to_payload(),
                "title": row["title"],
                "status": row["status"],
                "input": input_payload,
                "createdAt": row["created_at"],
                "startedAt": row["started_at"],
                "finishedAt": row["finished_at"],
                "errorCode": row["error_code"],
            },
            eval_pack_id=pack.id,
            eval_pack_version=pack.version,
            events=events,
            artifacts=artifacts,
            versions=versions,
            model_bindings=model_bindings,
            tool_versions=tool_versions,
            captured_at=datetime.now(timezone.utc).isoformat(),
        )

    def _event(self, event: dict[str, Any]) -> FrozenTraceEvent:
        try:
            content = self._read_all(event["run_id"], event["event_id"])
            available = True
        except (TraceContentNotFoundError, TraceContentUnavailableError):
            content = None
            available = False
        return FrozenTraceEvent(
            event_id=event["event_id"],
            operation_id=event["operation_id"],
            event_type=event["event_type"],
            observed_at=event["observed_at"],
            payload_sha256=event["payload_sha256"],
            sequence=event["sequence"],
            available=available,
            content=content,
        )

    def _read_all(self, run_id: str, event_id: str) -> str:
        offset = 0
        content: list[str] = []
        while True:
            page = self.service.content_reader.read(
                run_id=run_id,
                event_id=event_id,
                offset=offset,
                limit=65536,
            )
            content.append(page.content)
            if page.next_offset is None:
                return "".join(content)
            offset = page.next_offset


def _parse_object(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, (str, int, float))
    }


def _find_hashes(
    value: object, path: str = "input"
) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if (
                isinstance(key, str)
                and "hash" in key.casefold()
                and isinstance(item, str)
                and len(item) == 64
                and all(char in "0123456789abcdefABCDEF" for char in item)
            ):
                found.add((child_path, item.casefold()))
            found.update(_find_hashes(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.update(_find_hashes(item, f"{path}[{index}]"))
    return found
