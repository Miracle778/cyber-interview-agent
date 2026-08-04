from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from app.agents.definition_registry import AgentDefinition
from app.evaluation.registry import get_eval_pack


_LEGACY_JSON = '{"snapshot_version":1,"legacy":true}'


@dataclass(frozen=True, slots=True)
class AgentDefinitionSnapshot:
    snapshot_version: int
    legacy: bool
    agent_id: str | None = None
    agent_definition_version: str | None = None
    graph_version: int | None = None
    builder_key: str | None = None
    prompt_schema_versions: tuple[tuple[str, str], ...] = ()
    input_schema_version: str | None = None
    output_schema_version: str | None = None
    child_components: tuple[str, ...] = ()
    model_roles: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    allowed_scopes: tuple[str, ...] = ()
    toolset_digest: str | None = None
    model_binding_digest: str | None = None
    context_policy_id: str | None = None
    retry_policy_id: str | None = None
    trace_policy_id: str | None = None
    eval_pack_id: str | None = None
    eval_pack_version: int | None = None

    @classmethod
    def legacy_snapshot(cls) -> AgentDefinitionSnapshot:
        return cls(snapshot_version=1, legacy=True)

    def to_json(self) -> str:
        if self == self.legacy_snapshot():
            return _LEGACY_JSON
        return json.dumps(
            self.to_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_payload(self) -> dict[str, Any]:
        if self == self.legacy_snapshot():
            return {"snapshot_version": 1, "legacy": True}
        payload = asdict(self)
        payload["prompt_schema_versions"] = dict(self.prompt_schema_versions)
        return payload

    @classmethod
    def from_json(cls, raw: str) -> AgentDefinitionSnapshot:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("stored Agent Definition Snapshot must be an object")
        if payload.get("legacy") is True:
            return cls.legacy_snapshot()
        prompt_versions = payload.get("prompt_schema_versions") or {}
        if not isinstance(prompt_versions, dict):
            raise ValueError("prompt schema versions must be an object")
        tuple_fields = (
            "child_components",
            "model_roles",
            "allowed_tools",
            "allowed_scopes",
        )
        normalized = dict(payload)
        normalized["prompt_schema_versions"] = tuple(
            sorted((str(key), str(value)) for key, value in prompt_versions.items())
        )
        for field_name in tuple_fields:
            values = normalized.get(field_name) or ()
            if not isinstance(values, (list, tuple)):
                raise ValueError(f"{field_name} must be an array")
            normalized[field_name] = tuple(str(value) for value in values)
        try:
            snapshot = cls(**normalized)
        except TypeError as error:
            raise ValueError("stored Agent Definition Snapshot is invalid") from error
        if snapshot.snapshot_version != 1 or snapshot.legacy:
            raise ValueError("stored Agent Definition Snapshot version is invalid")
        if not snapshot.agent_id or not snapshot.agent_definition_version:
            raise ValueError("stored Agent Definition Snapshot identity is missing")
        return snapshot


def build_agent_definition_snapshot(
    *,
    definition: AgentDefinition,
    graph_version: int,
    model_bindings: Mapping[str, str],
) -> AgentDefinitionSnapshot:
    eval_pack_version = None
    if definition.eval_pack_id is not None:
        eval_pack_version = get_eval_pack(definition.eval_pack_id).version
    relevant_bindings = {
        role: model_bindings.get(role)
        for role in sorted(definition.model_roles)
    }
    tool_contract = {
        "allowed_scopes": sorted(definition.allowed_scopes),
        "allowed_tools": sorted(definition.allowed_tools),
    }
    return AgentDefinitionSnapshot(
        snapshot_version=1,
        legacy=False,
        agent_id=definition.agent_id,
        agent_definition_version=definition.definition_version,
        graph_version=graph_version,
        builder_key=definition.builder_key,
        prompt_schema_versions=tuple(sorted(definition.prompt_schema_versions)),
        input_schema_version=definition.input_schema_version,
        output_schema_version=definition.output_schema_version,
        child_components=tuple(sorted(definition.child_components)),
        model_roles=tuple(sorted(definition.model_roles)),
        allowed_tools=tuple(sorted(definition.allowed_tools)),
        allowed_scopes=tuple(sorted(definition.allowed_scopes)),
        toolset_digest=_digest(tool_contract),
        model_binding_digest=_digest(relevant_bindings),
        context_policy_id=definition.context_policy_id,
        retry_policy_id=definition.retry_policy_id,
        trace_policy_id=definition.trace_policy_id,
        eval_pack_id=definition.eval_pack_id,
        eval_pack_version=eval_pack_version,
    )


def _digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
