from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from app.agents.context_assembly import (
    ContextMaterial,
    ContextMessage,
    ContextResource,
    ContextSummary,
    ContextTurn,
    AssembledContext,
)
from app.agents.context import AgentContext
from app.application.session_service import MessageRecord
from app.review.curation_command_contracts import CurationCommandPlan
from app.review.curation_commands import CurationCommandService
from app.review.models import CurationSummary


class CommandClassifier(Protocol):
    async def classify(
        self, assembled: AssembledContext, *, context: AgentContext
    ) -> CurationCommandPlan: ...


ContextProvider = Callable[
    [], Awaitable[tuple[AssembledContext, AgentContext]]
]


@dataclass(frozen=True, slots=True)
class CurationCommandInterpreter:
    commands: CurationCommandService
    classifier: CommandClassifier

    async def interpret(
        self,
        *,
        text: str,
        summary: CurationSummary,
        focused_candidate_ids: tuple[str, ...],
        context_provider: ContextProvider,
    ) -> CurationCommandPlan:
        deterministic = self.commands.try_parse(
            text, summary, focused_candidate_ids
        )
        if deterministic is not None:
            return deterministic
        assembled, invocation_context = await context_provider()
        return await self.classifier.classify(
            assembled, context=invocation_context
        )


class CurationContextAdapter:
    @staticmethod
    def recover_focus(
        messages: Iterable[MessageRecord], valid_candidate_ids: set[str]
    ) -> tuple[str, ...]:
        for message in reversed(tuple(messages)):
            stored = message.payload.get("candidateIds")
            if not isinstance(stored, (list, tuple)):
                continue
            return tuple(
                dict.fromkeys(
                    str(candidate_id)
                    for candidate_id in stored
                    if str(candidate_id) in valid_candidate_ids
                )
            )
        return ()

    @staticmethod
    def focus_after(
        candidate_ids: Iterable[str], valid_candidate_ids: set[str]
    ) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                candidate_id
                for candidate_id in candidate_ids
                if candidate_id in valid_candidate_ids
            )
        )

    @classmethod
    def build_material(
        cls,
        *,
        current_input: str,
        summary_version: int,
        focused_candidate_ids: tuple[str, ...],
        prior_summary: ContextSummary,
        summarized_through_message_id: str | None,
        messages: tuple[MessageRecord, ...],
        candidates: tuple[dict[str, Any], ...],
    ) -> ContextMaterial:
        visible = tuple(
            message
            for message in messages
            if message.message_kind in {"text", "command_receipt"}
        )
        if summarized_through_message_id is not None:
            cursor = next(
                (
                    index
                    for index, message in enumerate(visible)
                    if message.id == summarized_through_message_id
                ),
                None,
            )
            if cursor is not None:
                visible = visible[cursor + 1 :]
        if (
            visible
            and visible[-1].role == "user"
            and visible[-1].content == current_input
        ):
            visible = visible[:-1]

        by_id = {
            str(item.get("id") or item.get("candidateId")): item
            for item in candidates
        }
        index_lines = [
            f"summaryVersion={summary_version}",
            "focusedCandidateIds=" + ",".join(focused_candidate_ids),
            "候选题轻量索引：",
        ]
        for item in sorted(candidates, key=lambda value: int(value["ordinal"])):
            note = str(
                item.get("review_note") or item.get("reviewNote") or ""
            ).strip()
            index_lines.append(
                f"{item['ordinal']}. id={item.get('id') or item.get('candidateId')} "
                f"title={item.get('title', '')} status={item.get('status', '')} "
                f"recommendation={item.get('recommendation', '')} "
                f"noted={'yes' if note else 'no'}"
            )

        resources = []
        for candidate_id in focused_candidate_ids:
            item = by_id.get(candidate_id)
            if item is None:
                continue
            question = item.get("question") or {}
            resources.append(
                ContextResource(
                    ref=f"candidate:{candidate_id}",
                    label=f"第 {item['ordinal']} 题 {item.get('title', '')}",
                    content="\n".join(
                        (
                            f"题目：{question.get('question_text', '')}",
                            f"参考答案：{question.get('reference_answer', '')}",
                            "关键点：" + "；".join(question.get("key_points") or ()),
                            "必要追问：" + "；".join(question.get("follow_ups") or ()),
                        )
                    ),
                    priority=0,
                    required=True,
                )
            )
        return ContextMaterial(
            current_input=current_input,
            working_state="\n".join(index_lines),
            prior_summary=prior_summary,
            turns=cls._turns(visible),
            resources=tuple(resources),
        )

    @staticmethod
    def _turns(messages: tuple[MessageRecord, ...]) -> tuple[ContextTurn, ...]:
        turns: list[ContextTurn] = []
        current: list[ContextMessage] = []
        for message in messages:
            projected = ContextMessage(
                id=message.id,
                role=message.role,
                content=message.content,
                resource_refs=tuple(
                    f"candidate:{candidate_id}"
                    for candidate_id in message.payload.get("candidateIds", ())
                ),
            )
            if message.role == "user" and current:
                turns.append(ContextTurn(tuple(current)))
                current = []
            current.append(projected)
        if current:
            turns.append(ContextTurn(tuple(current)))
        return tuple(turns)
