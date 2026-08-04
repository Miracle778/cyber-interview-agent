from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.messages.utils import count_tokens_approximately

from app.agents.prompts.interview_retrospective_prompts import render_chat_input


MessageTokenCounter = Callable[[Sequence[BaseMessage]], int]


@dataclass(frozen=True, slots=True)
class RetrospectiveChatContext:
    messages: tuple[BaseMessage, ...]
    included_complete_turns: int
    omitted_complete_turns: int
    estimated_history_tokens: int


def assemble_retrospective_chat_context(
    *,
    message: str,
    selected_question_id: str | None,
    conversation: Sequence[dict[str, Any]],
    history_token_budget: int,
    token_counter: MessageTokenCounter = count_tokens_approximately,
) -> RetrospectiveChatContext:
    if history_token_budget < 0:
        raise ValueError("history_token_budget must not be negative")

    complete_turns = _complete_turns(conversation)
    selected_reversed: list[tuple[BaseMessage, ...]] = []
    used_tokens = 0
    for turn in reversed(complete_turns):
        turn_tokens = max(1, int(token_counter(turn)))
        if used_tokens + turn_tokens > history_token_budget:
            break
        selected_reversed.append(turn)
        used_tokens += turn_tokens

    selected_turns = tuple(reversed(selected_reversed))
    omitted_turns = len(complete_turns) - len(selected_turns)
    history_messages = tuple(
        item for turn in selected_turns for item in turn
    )
    current = HumanMessage(
        content=render_chat_input(
            message=message,
            selected_question_id=selected_question_id,
            included_complete_turns=len(selected_turns),
            omitted_complete_turns=omitted_turns,
        )
    )
    return RetrospectiveChatContext(
        messages=(*history_messages, current),
        included_complete_turns=len(selected_turns),
        omitted_complete_turns=omitted_turns,
        estimated_history_tokens=used_tokens,
    )


def _complete_turns(
    conversation: Sequence[dict[str, Any]],
) -> tuple[tuple[BaseMessage, ...], ...]:
    turns: list[tuple[BaseMessage, ...]] = []
    current: list[BaseMessage] = []

    def finish_current() -> None:
        nonlocal current
        if current and any(isinstance(item, AIMessage) for item in current):
            turns.append(tuple(current))
        current = []

    for item in conversation:
        role = item.get("role")
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        message_id = item.get("id")
        stable_id = message_id if isinstance(message_id, str) else None
        if role == "user":
            finish_current()
            current = [HumanMessage(content=content, id=stable_id)]
        elif role == "assistant" and current:
            current.append(AIMessage(content=content, id=stable_id))

    finish_current()
    return tuple(turns)
