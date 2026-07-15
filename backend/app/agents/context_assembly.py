from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import HumanMessage
from langchain_core.messages.utils import count_tokens_approximately


TokenCounter = Callable[[str], int]


class ContextBudgetExceededError(RuntimeError):
    code = "context_budget_exceeded"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_input_tokens: int
    reserved_output_tokens: int = 0
    reserved_system_tokens: int = 0
    reserved_schema_tokens: int = 0
    reserved_tool_tokens: int = 0

    @property
    def available_input_tokens(self) -> int:
        values = (
            self.max_input_tokens,
            self.reserved_output_tokens,
            self.reserved_system_tokens,
            self.reserved_schema_tokens,
            self.reserved_tool_tokens,
        )
        if self.max_input_tokens <= 0 or any(value < 0 for value in values[1:]):
            raise ValueError("context token budgets must not be negative")
        available = self.max_input_tokens - sum(values[1:])
        if available <= 0:
            raise ContextBudgetExceededError()
        return available


@dataclass(frozen=True, slots=True)
class ContextMessage:
    id: str
    role: str
    content: str
    resource_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextTurn:
    messages: tuple[ContextMessage, ...]

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("context turn must contain messages")


@dataclass(frozen=True, slots=True)
class ContextResource:
    ref: str
    label: str
    content: str
    priority: int
    required: bool = False


@dataclass(frozen=True, slots=True)
class ContextSummary:
    text: str
    resource_refs: tuple[str, ...]
    decisions: tuple[str, ...]
    open_items: tuple[str, ...]
    through_message_id: str | None

    @classmethod
    def empty(cls) -> ContextSummary:
        return cls("", (), (), (), None)


@dataclass(frozen=True, slots=True)
class ContextMaterial:
    current_input: str
    working_state: str
    prior_summary: ContextSummary
    turns: tuple[ContextTurn, ...]
    resources: tuple[ContextResource, ...]


@dataclass(frozen=True, slots=True)
class AssembledContext:
    current_input: str
    working_state: str
    prior_summary: ContextSummary
    recent_turns: tuple[ContextTurn, ...]
    overflow_turns: tuple[ContextTurn, ...]
    selected_resources: tuple[ContextResource, ...]
    estimated_input_tokens: int
    threshold_tokens: int

    def render(self) -> str:
        return "\n\n".join(_render_fragments(
            current_input=self.current_input,
            working_state=self.working_state,
            summary=self.prior_summary,
            turns=self.recent_turns,
            resources=self.selected_resources,
        ))


class ContextAssembler:
    def assemble(
        self,
        material: ContextMaterial,
        budget: ContextBudget,
        token_counter: TokenCounter,
    ) -> AssembledContext:
        threshold = budget.available_input_tokens
        required_resources = tuple(
            sorted(
                (item for item in material.resources if item.required),
                key=lambda item: (item.priority, item.ref),
            )
        )
        optional_resources = tuple(
            sorted(
                (item for item in material.resources if not item.required),
                key=lambda item: (item.priority, item.ref),
            )
        )
        fixed_fragments = _render_fragments(
            current_input=material.current_input,
            working_state=material.working_state,
            summary=material.prior_summary,
            turns=(),
            resources=required_resources,
        )
        used = _count_fragments(fixed_fragments, token_counter)
        if used > threshold:
            raise ContextBudgetExceededError()

        recent_reversed: list[ContextTurn] = []
        overflow = material.turns
        for index in range(len(material.turns) - 1, -1, -1):
            turn = material.turns[index]
            cost = token_counter(_render_turn(turn))
            if used + cost > threshold:
                overflow = material.turns[: index + 1]
                break
            recent_reversed.append(turn)
            used += cost
            overflow = material.turns[:index]
        recent = tuple(reversed(recent_reversed))

        selected_optional: list[ContextResource] = []
        for resource in optional_resources:
            cost = token_counter(_render_resource(resource))
            if used + cost <= threshold:
                selected_optional.append(resource)
                used += cost
        selected_resources = required_resources + tuple(selected_optional)

        result = AssembledContext(
            current_input=material.current_input,
            working_state=material.working_state,
            prior_summary=material.prior_summary,
            recent_turns=recent,
            overflow_turns=overflow,
            selected_resources=selected_resources,
            estimated_input_tokens=0,
            threshold_tokens=threshold,
        )
        estimated = token_counter(result.render())
        if estimated > threshold:
            raise ContextBudgetExceededError()
        return AssembledContext(
            current_input=result.current_input,
            working_state=result.working_state,
            prior_summary=result.prior_summary,
            recent_turns=result.recent_turns,
            overflow_turns=result.overflow_turns,
            selected_resources=result.selected_resources,
            estimated_input_tokens=estimated,
            threshold_tokens=result.threshold_tokens,
        )


def model_token_counter(model) -> TokenCounter:
    def count(text: str) -> int:
        try:
            value = int(model.get_num_tokens(text))
            if value > 0:
                return value
        except Exception:
            pass
        return max(
            1,
            count_tokens_approximately([HumanMessage(content=text)]),
        )

    return count


def _render_fragments(
    *,
    current_input: str,
    working_state: str,
    summary: ContextSummary,
    turns: tuple[ContextTurn, ...],
    resources: tuple[ContextResource, ...],
) -> tuple[str, ...]:
    fragments = [f"当前输入\n{current_input}", f"工作状态\n{working_state}"]
    summary_text = _render_summary(summary)
    if summary_text:
        fragments.append(summary_text)
    fragments.extend(_render_turn(turn) for turn in turns)
    fragments.extend(_render_resource(resource) for resource in resources)
    return tuple(fragments)


def _render_summary(summary: ContextSummary) -> str:
    if not any(
        (
            summary.text,
            summary.resource_refs,
            summary.decisions,
            summary.open_items,
        )
    ):
        return ""
    lines = ["历史摘要", summary.text]
    lines.extend(f"资源引用 {item}" for item in summary.resource_refs)
    lines.extend(f"已定事项 {item}" for item in summary.decisions)
    lines.extend(f"未决事项 {item}" for item in summary.open_items)
    return "\n".join(line for line in lines if line)


def _render_turn(turn: ContextTurn) -> str:
    return "\n".join(
        part
        for message in turn.messages
        for part in (message.role, message.content)
    )


def _render_resource(resource: ContextResource) -> str:
    return f"资源 {resource.ref} {resource.label}\n{resource.content}"


def _count_fragments(
    fragments: tuple[str, ...], token_counter: TokenCounter
) -> int:
    return sum(token_counter(fragment) for fragment in fragments)
