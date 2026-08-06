from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.agents.agent_factory import AgentSpec, RegisteredAgentFactory
from app.agents.agent_invocation import isolated_thread_config
from app.agents.agent_model_resolver import ModelInvocationPolicy
from app.agents.agent_protocols import AgentRunnable
from app.agents.context import AgentContext
from app.agents.prompts.question_curation_prompts import (
    QUESTION_COVERAGE_AUDIT_PROMPT,
    QUESTION_DISCOVERY_PROMPT,
    QUESTION_ENRICHMENT_PROMPT,
    QUESTION_REVISION_PROMPT,
    render_question_coverage_audit_input,
    render_question_discovery_input,
    render_question_enrichment_input,
    render_question_revision_input,
)
from app.agents.question_curation_contracts import (
    CoverageAuditChunk,
    ProviderCoverageAuditChunk,
    ProviderQuestionCandidateChunk,
    ProviderQuestionSeedChunk,
    QuestionSeed,
    QuestionSeedChunk,
    normalize_provider_coverage_audit_chunk,
    normalize_provider_seed_chunk,
)
from app.review.curation_sections import SourceSection
from app.review.models import CurationSeedTaskRecord


_DISCOVERY_POLICY = ModelInvocationPolicy(2_048, 90, 1)
_COVERAGE_AUDIT_POLICY = ModelInvocationPolicy(2_048, 90, 1)
_ENRICHMENT_POLICY = ModelInvocationPolicy(4_096, 180, 1)
_REVISION_POLICY = ModelInvocationPolicy(4_096, 180, 0)
_MARKDOWN_HEADING_ONLY = re.compile(r"^\s{0,3}#{1,6}\s+\S.*$")
_BOLD_HEADING_ONLY = re.compile(r"^\s*(?:\*\*|__)\S.+(?:\*\*|__)\s*$")
_EXPLICIT_ZERO_QUESTION_PATTERNS = (
    re.compile(r"未(?:发现|找到|识别出|提取出).{0,40}(?:面试题|候选题|题目|问题)"),
    re.compile(
        r"(?:材料|片段|内容).{0,30}(?:未包含|不包含|没有).{0,30}(?:面试题|候选题|题目|问题)"
    ),
    re.compile(
        r"没有.{0,30}(?:可识别|可提取|适合生成).{0,20}(?:面试题|候选题|题目|问题)"
    ),
    re.compile(r"\bno\s+(?:interview\s+)?questions?\b", re.IGNORECASE),
    re.compile(r"\bdoes\s+not\s+contain.{0,30}questions?\b", re.IGNORECASE),
)


class ModelOutputTruncatedError(RuntimeError):
    """The Provider exhausted output budget before returning the schema."""

    code = "output_truncated"

    def __init__(self) -> None:
        super().__init__("模型输出在结构化结果完成前被截断")


class ModelStructuredOutputMissingError(RuntimeError):
    """The Provider answered, but did not return the requested schema."""

    code = "structured_output_missing"

    def __init__(self) -> None:
        super().__init__("模型未按约定返回结构化题目结果")


@dataclass(frozen=True, slots=True)
class QuestionCurationAgents:
    discovery: AgentRunnable
    enrichment: AgentRunnable
    revision: AgentRunnable
    coverage_audit: AgentRunnable | None = None

    @classmethod
    def create(
        cls,
        factory: RegisteredAgentFactory,
        *,
        model_bindings: Mapping[str, str],
        middleware: tuple[AgentMiddleware, ...] = (),
        tools=(),
        checkpointer=None,
    ) -> "QuestionCurationAgents":
        common = {
            "model_bindings": model_bindings,
            "checkpointer": checkpointer,
        }
        return cls(
            discovery=factory.create(
                AgentSpec(
                    role="question_generation",
                    execution_name="question_discovery",
                    prompt=QUESTION_DISCOVERY_PROMPT,
                    middleware=middleware,
                    response_format=ProviderQuestionSeedChunk,
                    structured_output_handle_errors=False,
                    invocation_policy=_DISCOVERY_POLICY,
                ),
                component_id="question_discovery",
                **common,
            ),
            enrichment=factory.create(
                AgentSpec(
                    role="question_generation",
                    execution_name="question_enrichment",
                    prompt=QUESTION_ENRICHMENT_PROMPT,
                    tools=tuple(tools),
                    middleware=middleware,
                    response_format=ProviderQuestionCandidateChunk,
                    structured_output_handle_errors=False,
                    invocation_policy=_ENRICHMENT_POLICY,
                ),
                component_id="question_enrichment",
                **common,
            ),
            revision=factory.create(
                AgentSpec(
                    role="question_generation",
                    execution_name="question_revision",
                    prompt=QUESTION_REVISION_PROMPT,
                    tools=tuple(tools),
                    middleware=middleware,
                    response_format=ProviderQuestionCandidateChunk,
                    structured_output_handle_errors=False,
                    invocation_policy=_REVISION_POLICY,
                ),
                component_id="question_revision",
                **common,
            ),
            coverage_audit=factory.create(
                AgentSpec(
                    role="question_generation",
                    execution_name="question_coverage_audit",
                    prompt=QUESTION_COVERAGE_AUDIT_PROMPT,
                    middleware=middleware,
                    response_format=ProviderCoverageAuditChunk,
                    structured_output_handle_errors=False,
                    invocation_policy=_COVERAGE_AUDIT_POLICY,
                ),
                component_id="question_coverage_audit",
                **common,
            ),
        )

    async def discover(
        self,
        sections: Sequence[SourceSection],
        *,
        context: AgentContext,
        config: dict[str, Any],
        unit_index: int,
    ) -> QuestionSeedChunk:
        if all(_heading_only(section.text) for section in sections):
            return QuestionSeedChunk(seeds=[])
        result = await self.discovery.ainvoke(
            {
                "messages": [
                    HumanMessage(content=render_question_discovery_input(sections))
                ]
            },
            isolated_thread_config(
                config, context, f"question_discovery:{context.run_id}:{unit_index}"
            ),
            context=context,
        )
        chunk = normalize_provider_seed_chunk(_discovery_structured(result))
        allowed = {section.ref: section.source_id for section in sections}
        seeds: list[QuestionSeed] = []
        seen_refs: set[str] = set()
        for seed in chunk.seeds:
            if any(ref not in allowed for ref in seed.source_refs):
                raise ValueError("question discovery returned an unknown source ref")
            if len({allowed[ref] for ref in seed.source_refs}) != 1:
                raise ValueError("question discovery returned cross-source refs")
            if seed.source_ref in seen_refs:
                continue
            seen_refs.add(seed.source_ref)
            seeds.append(seed)
        return chunk.model_copy(update={"seeds": seeds})

    async def audit(
        self,
        sections: Sequence[SourceSection],
        *,
        discovered_seeds: Sequence[QuestionSeed],
        context: AgentContext,
        config: dict[str, Any],
        unit_index: int,
    ) -> CoverageAuditChunk:
        runnable = self.coverage_audit or self.discovery
        result = await runnable.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_question_coverage_audit_input(
                            sections, discovered_seeds=discovered_seeds
                        )
                    )
                ]
            },
            isolated_thread_config(
                config,
                context,
                f"question_coverage_audit:{context.run_id}:{unit_index}",
            ),
            context=context,
        )
        chunk = normalize_provider_coverage_audit_chunk(_discovery_structured(result))
        allowed = {section.ref: section.source_id for section in sections}
        seen_seeds: set[tuple[str, str]] = set()
        seeds = []
        for seed in chunk.seeds:
            valid_refs = [ref for ref in seed.source_refs if ref in allowed]
            if not valid_refs:
                continue
            primary = seed.source_ref if seed.source_ref in allowed else valid_refs[0]
            source_id = allowed[primary]
            bounded_refs = [
                primary,
                *(
                    ref
                    for ref in valid_refs
                    if ref != primary and allowed[ref] == source_id
                ),
            ]
            seed_key = (seed.question_text.casefold(), primary)
            if seed_key in seen_seeds:
                continue
            seen_seeds.add(seed_key)
            seeds.append(
                seed.model_copy(
                    update={
                        "source_ref": primary,
                        "source_refs": bounded_refs,
                    }
                )
            )
        return chunk.model_copy(update={"seeds": seeds})

    async def enrich(
        self,
        seeds: Sequence[QuestionSeed | CurationSeedTaskRecord],
        *,
        sections: Sequence[SourceSection],
        known_questions: Sequence[str],
        context: AgentContext,
        config: dict[str, Any],
        unit_index: int,
    ) -> ProviderQuestionCandidateChunk:
        allowed = {section.ref: section.source_id for section in sections}
        seed_refs = {_seed_primary_ref(seed): tuple(seed.source_refs) for seed in seeds}
        for seed in seeds:
            if any(ref not in allowed for ref in seed.source_refs):
                raise ValueError("question enrichment received an unknown source ref")
            if len({allowed[ref] for ref in seed.source_refs}) != 1:
                raise ValueError("question enrichment received cross-source refs")
        result = await self.enrichment.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_question_enrichment_input(
                            seeds, sections=sections, known_questions=known_questions
                        )
                    )
                ]
            },
            isolated_thread_config(
                config, context, f"question_enrichment:{context.run_id}:{unit_index}"
            ),
            context=context,
        )
        structured = _structured(result)
        if hasattr(structured, "model_dump"):
            structured = structured.model_dump()
        return ProviderQuestionCandidateChunk.model_validate(structured)

    async def revise(
        self,
        *,
        source_excerpts: Sequence[str],
        rewrite_feedback: str,
        seed: CurationSeedTaskRecord | None = None,
        context: AgentContext,
        config: dict[str, Any],
    ) -> ProviderQuestionCandidateChunk:
        result = await self.revision.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_question_revision_input(
                            source_excerpts,
                            rewrite_feedback=rewrite_feedback,
                            seed=seed,
                        )
                    )
                ]
            },
            isolated_thread_config(
                config, context, f"question_revision:{context.run_id}"
            ),
            context=context,
        )
        structured = _structured(result)
        if hasattr(structured, "model_dump"):
            structured = structured.model_dump()
        return ProviderQuestionCandidateChunk.model_validate(structured)


def _structured(result: object) -> object:
    if not isinstance(result, dict):
        raise ModelStructuredOutputMissingError()
    structured = result.get("structured_response")
    if structured is not None:
        return structured
    if _result_stop_reason(result) in {"max_tokens", "length", "max_output_tokens"}:
        raise ModelOutputTruncatedError()
    raise ModelStructuredOutputMissingError()


def _discovery_structured(result: object) -> object:
    try:
        return _structured(result)
    except ModelStructuredOutputMissingError:
        if _explicit_zero_question_response(result):
            return {"seeds": []}
        raise


def _explicit_zero_question_response(result: object) -> bool:
    if not isinstance(result, Mapping):
        return False
    text = _result_text(result).strip()
    if not text or len(text) > 240 or any(mark in text for mark in ("?", "？")):
        return False
    return any(pattern.search(text) for pattern in _EXPLICIT_ZERO_QUESTION_PATTERNS)


def _result_text(result: Mapping[str, object]) -> str:
    candidates: list[object] = []
    for key in ("result", "messages", "output"):
        value = result.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            candidates.extend(value)
        elif value is not None:
            candidates.append(value)
    parts: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if content is None and isinstance(candidate, Mapping):
            content = candidate.get("content") or candidate.get("text")
        if isinstance(content, str):
            parts.append(content)
            continue
        if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
            continue
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
    return "\n".join(parts)


def _result_stop_reason(result: Mapping[str, object]) -> str | None:
    candidates: list[object] = []
    for key in ("result", "messages", "output"):
        value = result.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            candidates.extend(value)
        elif value is not None:
            candidates.append(value)
    for candidate in reversed(candidates):
        metadata = getattr(candidate, "response_metadata", None)
        if not isinstance(metadata, Mapping):
            continue
        raw = metadata.get("stop_reason") or metadata.get("finish_reason")
        if isinstance(raw, str) and raw.strip():
            return raw.strip().casefold()
    return None


def _heading_only(text: str) -> bool:
    lines = tuple(line.strip() for line in text.splitlines() if line.strip())
    if not lines:
        return True
    if len(lines) > 1:
        return all(
            _MARKDOWN_HEADING_ONLY.fullmatch(line) or _BOLD_HEADING_ONLY.fullmatch(line)
            for line in lines
        )
    line = lines[0]
    return bool(
        _MARKDOWN_HEADING_ONLY.fullmatch(line) or _BOLD_HEADING_ONLY.fullmatch(line)
    )


def _seed_primary_ref(seed: QuestionSeed | CurationSeedTaskRecord) -> str:
    return (
        seed.primary_source_ref
        if isinstance(seed, CurationSeedTaskRecord)
        else seed.source_ref
    )
