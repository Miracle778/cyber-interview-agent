from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import frontmatter
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool
from langchain.tools import ToolRuntime
from pydantic import BaseModel, ConfigDict, Field

from app.agents.context import AgentContext
from app.profile.repository import ProfileRepository
from app.profile.storage import MaterialStorage
from app.security.workspace_paths import PathPolicyError, WorkspacePathPolicy


MAX_PROFILE_TOOL_ITEMS = 50
MAX_PROFILE_EXCERPT_CHARS = 2000

PROFILE_TOOL_NAMES = (
    "list_personal_materials",
    "search_personal_materials",
    "read_personal_evidence",
    "get_profile_claims",
    "get_profile_claim_evidence",
    "compare_material_versions",
    "search_active_knowledge",
    "get_profile_publication_status",
)

PROFILE_TOOL_SCOPES = {
    "list_personal_materials": "profile.materials",
    "search_personal_materials": "profile.materials",
    "read_personal_evidence": "profile.materials",
    "get_profile_claims": "profile.materials",
    "get_profile_claim_evidence": "profile.materials",
    "compare_material_versions": "profile.materials",
    "search_active_knowledge": "knowledge.active",
    "get_profile_publication_status": "profile.materials",
}


@dataclass(frozen=True, slots=True)
class ProfileChatBudget:
    max_calls: int
    max_identical_calls: int


PROFILE_CHAT_BUDGET = ProfileChatBudget(max_calls=6, max_identical_calls=2)


class _StrictInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        arbitrary_types_allowed=True,
    )
    # Keep runtime in the validation schema so ToolNode can detect and inject it.
    # It is an injected marker and is therefore excluded from the model-visible
    # tool call schema.
    runtime: ToolRuntime[AgentContext]


class NoInput(_StrictInput):
    pass


class SearchInput(_StrictInput):
    query: str = Field(min_length=1, max_length=200)


class EvidenceInput(_StrictInput):
    evidence_id: str = Field(min_length=1, max_length=128)


class ClaimInput(_StrictInput):
    claim_id: str = Field(min_length=1, max_length=128)


class VersionCompareInput(_StrictInput):
    version_a_id: str = Field(min_length=1, max_length=128)
    version_b_id: str = Field(min_length=1, max_length=128)


class ToolEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_PROFILE_TOOL_ITEMS)
    evidenceRefs: list[dict[str, Any]] = Field(
        default_factory=list, max_length=MAX_PROFILE_TOOL_ITEMS
    )
    truncated: bool = False
    nextCursor: str | None = None
    state: str | None = None
    errorCode: str | None = None


def _envelope(**values: Any) -> dict[str, Any]:
    return ToolEnvelope(**values).model_dump(mode="json", exclude_none=True)


def _error(code: str) -> dict[str, Any]:
    return _envelope(status="error", errorCode=code)


def _limit(context: AgentContext) -> int:
    return max(1, min(MAX_PROFILE_TOOL_ITEMS, context.tool_result_item_limit))


def _excerpt(context: AgentContext, value: str) -> tuple[str, bool]:
    limit = max(1, min(MAX_PROFILE_EXCERPT_CHARS, context.tool_excerpt_char_limit))
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized, False
    return normalized[:limit].rstrip() + "…", True


def _authorized(context: AgentContext, tool_name: str) -> dict[str, Any] | None:
    if tool_name not in context.allowed_tools:
        return _error("tool_not_allowed")
    scope = PROFILE_TOOL_SCOPES[tool_name]
    if scope not in context.allowed_scopes:
        return _error("tool_scope_denied")
    return None


def list_personal_materials(
    repository: ProfileRepository, context: AgentContext
) -> dict[str, Any]:
    if denied := _authorized(context, "list_personal_materials"):
        return denied
    limit = _limit(context)
    materials = repository.list_materials(context.workspace_id)
    items: list[dict[str, Any]] = []
    for material in materials[:limit]:
        versions = repository.list_material_versions(material.id)[:limit]
        items.append(
            {
                "id": material.id,
                "workspaceId": material.workspace_id,
                "type": material.type,
                "title": material.title,
                "primaryRole": material.primary_role == "resume",
                "role": material.primary_role,
                "currentVersionId": material.current_version_id,
                "lifecycleStatus": material.lifecycle_status,
                "versions": [
                    {
                        "id": version.id,
                        "versionNumber": version.version_number,
                        "fileName": version.file_name,
                        "mimeType": version.mime_type,
                        "processingStatus": version.processing_status,
                        "createdAt": version.created_at,
                    }
                    for version in versions
                ],
            }
        )
    return _envelope(
        status="ok", items=items, truncated=len(materials) > limit
    )


def search_personal_materials(
    repository: ProfileRepository, context: AgentContext, *, query: str
) -> dict[str, Any]:
    if denied := _authorized(context, "search_personal_materials"):
        return denied
    query = query.strip()
    if not query:
        return _error("tool_input_invalid")
    limit = _limit(context)
    rows = repository.connection.execute(
        "SELECT e.id AS evidence_id, e.material_version_id, e.section, "
        "e.start_offset, e.end_offset, e.sanitized_text, e.sensitivity, "
        "m.id AS material_id, m.title, v.version_number "
        "FROM profile_evidence e "
        "JOIN profile_material_versions v ON v.id = e.material_version_id "
        "JOIN profile_materials m ON m.id = v.material_id "
        "WHERE m.workspace_id = ? AND m.lifecycle_status = 'active' "
        "AND e.tombstoned_at IS NULL "
        "AND (instr(lower(e.sanitized_text), lower(?)) > 0 "
        "OR instr(lower(m.title), lower(?)) > 0 "
        "OR instr(lower(v.file_name), lower(?)) > 0) "
        "ORDER BY m.updated_at DESC, v.version_number DESC, e.start_offset, e.id "
        "LIMIT ?",
        (context.workspace_id, query, query, query, limit + 1),
    ).fetchall()
    items = []
    excerpt_truncated = False
    for row in rows[:limit]:
        excerpt, clipped = _excerpt(context, row["sanitized_text"])
        excerpt_truncated = excerpt_truncated or clipped
        items.append(
            {
                "materialId": row["material_id"],
                "materialTitle": row["title"],
                "materialVersionId": row["material_version_id"],
                "versionNumber": int(row["version_number"]),
                "evidenceId": row["evidence_id"],
                "section": row["section"],
                "startOffset": int(row["start_offset"]),
                "endOffset": int(row["end_offset"]),
                "excerpt": excerpt,
                "sensitivity": row["sensitivity"],
            }
        )
    return _envelope(
        status="ok",
        items=items,
        truncated=len(rows) > limit or excerpt_truncated,
    )


def read_personal_evidence(
    repository: ProfileRepository,
    context: AgentContext,
    *,
    evidence_id: str,
) -> dict[str, Any]:
    if denied := _authorized(context, "read_personal_evidence"):
        return denied
    row = repository.connection.execute(
        "SELECT e.*, m.id AS material_id, m.title AS material_title, "
        "v.version_number "
        "FROM profile_evidence e "
        "JOIN profile_material_versions v ON v.id = e.material_version_id "
        "JOIN profile_materials m ON m.id = v.material_id "
        "WHERE e.id = ? AND e.tombstoned_at IS NULL "
        "AND m.workspace_id = ? AND m.lifecycle_status = 'active'",
        (evidence_id, context.workspace_id),
    ).fetchone()
    if row is None:
        return _error("profile_evidence_mismatch")
    excerpt, truncated = _excerpt(context, row["sanitized_text"])
    return _envelope(
        status="ok",
        items=[
            {
                "id": row["id"],
                "materialId": row["material_id"],
                "materialTitle": row["material_title"],
                "materialVersionId": row["material_version_id"],
                "versionNumber": int(row["version_number"]),
                "section": row["section"],
                "startOffset": int(row["start_offset"]),
                "endOffset": int(row["end_offset"]),
                "sanitizedText": excerpt,
                "sensitivity": row["sensitivity"],
            }
        ],
        truncated=truncated,
    )


def get_profile_claims(
    repository: ProfileRepository, context: AgentContext
) -> dict[str, Any]:
    if denied := _authorized(context, "get_profile_claims"):
        return denied
    snapshot = repository.profile_snapshot(context.workspace_id)
    limit = _limit(context)
    items = [
        {
            "id": claim.claim_id,
            "type": claim.claim_type,
            "claimVersionId": claim.claim_version_id,
            "versionNumber": claim.version_number,
            "value": claim.value,
            "supportStatus": claim.support_status,
            "evidenceIds": list(claim.evidence_ids[:limit]),
        }
        for claim in snapshot.claims[:limit]
    ]
    return _envelope(
        status="ok", items=items, truncated=len(snapshot.claims) > limit
    )


def get_profile_claim_evidence(
    repository: ProfileRepository, context: AgentContext, *, claim_id: str
) -> dict[str, Any]:
    if denied := _authorized(context, "get_profile_claim_evidence"):
        return denied
    row = repository.connection.execute(
        "SELECT v.evidence_ids_json FROM profile_claims c "
        "JOIN profile_claim_versions v ON v.id = c.current_confirmed_version_id "
        "WHERE c.id = ? AND c.workspace_id = ? AND v.status = 'confirmed'",
        (claim_id, context.workspace_id),
    ).fetchone()
    if row is None:
        return _error("profile_claim_not_found")
    evidence_ids = tuple(json.loads(row["evidence_ids_json"]))
    limit = _limit(context)
    refs: list[dict[str, Any]] = []
    clipped = False
    for evidence_id in evidence_ids[:limit]:
        evidence = repository.connection.execute(
            "SELECT e.*, m.id AS material_id, v.version_number "
            "FROM profile_evidence e "
            "JOIN profile_material_versions v ON v.id = e.material_version_id "
            "JOIN profile_materials m ON m.id = v.material_id "
            "WHERE e.id = ? AND e.tombstoned_at IS NULL "
            "AND m.workspace_id = ? AND m.lifecycle_status = 'active'",
            (evidence_id, context.workspace_id),
        ).fetchone()
        if evidence is None:
            continue
        excerpt, was_clipped = _excerpt(context, evidence["sanitized_text"])
        clipped = clipped or was_clipped
        refs.append(
            {
                "id": evidence["id"],
                "materialId": evidence["material_id"],
                "materialVersionId": evidence["material_version_id"],
                "versionNumber": int(evidence["version_number"]),
                "section": evidence["section"],
                "startOffset": int(evidence["start_offset"]),
                "endOffset": int(evidence["end_offset"]),
                "excerpt": excerpt,
                "sensitivity": evidence["sensitivity"],
            }
        )
    return _envelope(
        status="ok",
        evidenceRefs=refs,
        truncated=len(evidence_ids) > limit or clipped,
    )


def compare_material_versions(
    repository: ProfileRepository,
    context: AgentContext,
    *,
    version_a_id: str,
    version_b_id: str,
) -> dict[str, Any]:
    if denied := _authorized(context, "compare_material_versions"):
        return denied
    rows = repository.connection.execute(
        "SELECT v.*, m.workspace_id, m.lifecycle_status "
        "FROM profile_material_versions v "
        "JOIN profile_materials m ON m.id = v.material_id "
        "WHERE v.id IN (?, ?) AND m.workspace_id = ? "
        "AND m.lifecycle_status = 'active' ORDER BY v.id",
        (version_a_id, version_b_id, context.workspace_id),
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    if version_a_id not in by_id or version_b_id not in by_id:
        return _error("profile_material_version_not_found")
    a, b = by_id[version_a_id], by_id[version_b_id]
    if a["material_id"] != b["material_id"]:
        return _error("profile_material_version_mismatch")
    evidence_counts = {
        row["material_version_id"]: int(row["count"])
        for row in repository.connection.execute(
            "SELECT material_version_id, COUNT(*) AS count FROM profile_evidence "
            "WHERE material_version_id IN (?, ?) AND tombstoned_at IS NULL "
            "GROUP BY material_version_id",
            (version_a_id, version_b_id),
        ).fetchall()
    }
    return _envelope(
        status="ok",
        items=[
            {
                "materialId": a["material_id"],
                "versionAId": a["id"],
                "versionA": int(a["version_number"]),
                "versionBId": b["id"],
                "versionB": int(b["version_number"]),
                "sameContent": a["content_sha256"] == b["content_sha256"],
                "processingStatusA": a["processing_status"],
                "processingStatusB": b["processing_status"],
                "evidenceCountA": evidence_counts.get(a["id"], 0),
                "evidenceCountB": evidence_counts.get(b["id"], 0),
            }
        ],
    )


def search_active_knowledge(
    repository: ProfileRepository,
    context: AgentContext,
    *,
    query: str,
) -> dict[str, Any]:
    del repository
    if denied := _authorized(context, "search_active_knowledge"):
        return denied
    query = query.strip()
    if not query:
        return _error("tool_input_invalid")
    limit = _limit(context)
    try:
        policy = WorkspacePathPolicy(context.workspace_root)
        vault = policy.scope_root("knowledge.active")
    except PathPolicyError:
        return _error("knowledge_active_unavailable")
    matches: list[dict[str, Any]] = []
    clipped = False
    for candidate in sorted(vault.rglob("*.md"), key=lambda item: item.as_posix()):
        relative = candidate.relative_to(vault).as_posix()
        try:
            safe_path = policy.resolve_for_read("knowledge.active", relative)
            post = frontmatter.load(safe_path)
        except (OSError, ValueError, PathPolicyError):
            continue
        ingestion = post.metadata.get("ingestion")
        if (
            post.metadata.get("status") != "ingested"
            or not isinstance(ingestion, dict)
            or ingestion.get("confirmed_by_user") is not True
        ):
            continue
        title = str(post.metadata.get("title", ""))
        body = str(post.content)
        folded_query = query.casefold()
        if folded_query not in title.casefold() and folded_query not in body.casefold():
            continue
        excerpt, was_clipped = _excerpt(context, _matching_excerpt(body, query))
        clipped = clipped or was_clipped
        matches.append(
            {
                "id": str(post.metadata.get("id", "")),
                "type": str(post.metadata.get("type", "")),
                "title": title,
                "path": relative,
                "excerpt": excerpt,
            }
        )
        if len(matches) > limit:
            break
    return _envelope(
        status="ok",
        items=matches[:limit],
        truncated=len(matches) > limit or clipped,
    )


def _matching_excerpt(body: str, query: str) -> str:
    folded = body.casefold()
    index = folded.find(query.casefold())
    if index < 0:
        return body
    return body[max(0, index - 300) : index + len(query) + 700]


def get_profile_publication_status(
    repository: ProfileRepository, context: AgentContext
) -> dict[str, Any]:
    if denied := _authorized(context, "get_profile_publication_status"):
        return denied
    limit = _limit(context)
    rows = repository.connection.execute(
        "SELECT id, selection_id, profile_version, state, published_hash, "
        "revoked_at, created_at, updated_at FROM profile_publications "
        "WHERE workspace_id = ? ORDER BY updated_at DESC, id LIMIT ?",
        (context.workspace_id, limit + 1),
    ).fetchall()
    items = [
        {
            "id": row["id"],
            "selectionId": row["selection_id"],
            "profileVersion": row["profile_version"],
            "state": row["state"],
            "publishedHash": row["published_hash"],
            "revokedAt": row["revoked_at"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        for row in rows[:limit]
    ]
    return _envelope(
        status="ok",
        items=items,
        state=items[0]["state"] if items else "unpublished",
        truncated=len(rows) > limit,
    )


def create_profile_tools(
    *, repository: ProfileRepository, storage: MaterialStorage
) -> tuple[BaseTool, ...]:
    # Storage is deliberately injected with the repository even though R3's
    # read-only surface never reads whole private documents. This keeps future
    # bounded readers behind the same application-owned dependency boundary.
    _storage = storage

    @tool("list_personal_materials", args_schema=NoInput)
    def list_tool(runtime: ToolRuntime[AgentContext]) -> dict[str, Any]:
        """List active personal materials and bounded version metadata."""
        return list_personal_materials(repository, runtime.context)

    @tool("search_personal_materials", args_schema=SearchInput)
    def search_materials_tool(
        query: str, runtime: ToolRuntime[AgentContext]
    ) -> dict[str, Any]:
        """Search bounded sanitized Evidence excerpts in personal materials."""
        return search_personal_materials(repository, runtime.context, query=query)

    @tool("read_personal_evidence", args_schema=EvidenceInput)
    def evidence_tool(
        evidence_id: str, runtime: ToolRuntime[AgentContext]
    ) -> dict[str, Any]:
        """Read one bounded sanitized Evidence excerpt by stable ID."""
        return read_personal_evidence(
            repository, runtime.context, evidence_id=evidence_id
        )

    @tool("get_profile_claims", args_schema=NoInput)
    def claims_tool(runtime: ToolRuntime[AgentContext]) -> dict[str, Any]:
        """Get confirmed profile claims for the current Workspace."""
        return get_profile_claims(repository, runtime.context)

    @tool("get_profile_claim_evidence", args_schema=ClaimInput)
    def claim_evidence_tool(
        claim_id: str, runtime: ToolRuntime[AgentContext]
    ) -> dict[str, Any]:
        """Get bounded Evidence references for one confirmed Claim."""
        return get_profile_claim_evidence(
            repository, runtime.context, claim_id=claim_id
        )

    @tool("compare_material_versions", args_schema=VersionCompareInput)
    def compare_tool(
        version_a_id: str,
        version_b_id: str,
        runtime: ToolRuntime[AgentContext],
    ) -> dict[str, Any]:
        """Compare bounded metadata for two versions of one material."""
        return compare_material_versions(
            repository,
            runtime.context,
            version_a_id=version_a_id,
            version_b_id=version_b_id,
        )

    @tool("search_active_knowledge", args_schema=SearchInput)
    def knowledge_tool(
        query: str, runtime: ToolRuntime[AgentContext]
    ) -> dict[str, Any]:
        """Search user-confirmed active knowledge with bounded excerpts."""
        return search_active_knowledge(repository, runtime.context, query=query)

    @tool("get_profile_publication_status", args_schema=NoInput)
    def publication_tool(runtime: ToolRuntime[AgentContext]) -> dict[str, Any]:
        """Get the current Profile publication state and safe receipts."""
        return get_profile_publication_status(repository, runtime.context)

    del _storage
    return (
        list_tool,
        search_materials_tool,
        evidence_tool,
        claims_tool,
        claim_evidence_tool,
        compare_tool,
        knowledge_tool,
        publication_tool,
    )


class ProfileToolBudgetMiddleware(AgentMiddleware):
    """Per-Execution bounded Tool loop with normalized repeat detection."""

    def __init__(self, budget: ProfileChatBudget = PROFILE_CHAT_BUDGET) -> None:
        self._budget = budget
        self._executions: OrderedDict[
            tuple[str, str, str], tuple[int, dict[str, int]]
        ] = OrderedDict()
        # LangGraph may dispatch several Tool calls from one model response in
        # parallel. Profile tools share the workspace SQLite database for audit
        # and product events, so keep each Execution's Tool lifecycle ordered.
        self._execution_locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    async def awrap_tool_call(self, request, handler):
        context: AgentContext = request.runtime.context
        call = request.tool_call
        key = (context.workspace_id, context.session_id, context.run_id)
        fingerprint = self._fingerprint(call["name"], call.get("args", {}) or {})
        total, repeated = self._executions.get(key, (0, {}))
        if total >= self._budget.max_calls:
            return self._blocked(call, "profile_tool_budget_exhausted")
        if repeated.get(fingerprint, 0) >= self._budget.max_identical_calls:
            return self._blocked(call, "profile_tool_repeated_call")

        next_repeated = dict(repeated)
        next_repeated[fingerprint] = next_repeated.get(fingerprint, 0) + 1
        self._executions[key] = (total + 1, next_repeated)
        self._executions.move_to_end(key)
        while len(self._executions) > 1000:
            stale_key, _ = self._executions.popitem(last=False)
            stale_lock = self._execution_locks.get(stale_key)
            if stale_lock is not None and not stale_lock.locked():
                self._execution_locks.pop(stale_key, None)

        lock = self._execution_locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await handler(request)

    @staticmethod
    def _fingerprint(tool_name: str, args: object) -> str:
        normalized = json.dumps(
            args, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        return sha256(f"{tool_name}:{normalized}".encode("utf-8")).hexdigest()

    @staticmethod
    def _blocked(call: dict[str, Any], code: str) -> ToolMessage:
        return ToolMessage(
            content=f"{code}; answer with available context or ask for clarification",
            name=call["name"],
            tool_call_id=call.get("id"),
            status="error",
        )
