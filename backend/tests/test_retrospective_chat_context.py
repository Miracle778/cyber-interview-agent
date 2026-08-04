from __future__ import annotations

import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agents.retrospective_chat_context import (
    assemble_retrospective_chat_context,
)


def _fixed_tokens(messages: list[BaseMessage] | tuple[BaseMessage, ...]) -> int:
    return sum(int(message.additional_kwargs.get("test_tokens", 1)) for message in messages)


def test_chat_context_keeps_newest_complete_turns_as_role_messages() -> None:
    context = assemble_retrospective_chat_context(
        message="这道题哪里答得不好？",
        selected_question_id="question-1",
        conversation=(
            {"id": "user-1", "role": "user", "content": "先解释第一题"},
            {"id": "assistant-1", "role": "assistant", "content": "第一题解释"},
            {"id": "user-2", "role": "user", "content": "再解释第二题"},
            {"id": "assistant-2", "role": "assistant", "content": "第二题解释"},
            {"id": "user-unfinished", "role": "user", "content": "未完成的问题"},
        ),
        history_token_budget=2,
        token_counter=_fixed_tokens,
    )

    assert [type(message) for message in context.messages] == [
        HumanMessage,
        AIMessage,
        HumanMessage,
    ]
    assert [message.id for message in context.messages[:-1]] == [
        "user-2",
        "assistant-2",
    ]
    assert context.included_complete_turns == 1
    assert context.omitted_complete_turns == 1
    assert context.estimated_history_tokens == 2
    payload = json.loads(str(context.messages[-1].content))
    assert payload == {
        "message": "这道题哪里答得不好？",
        "selectedQuestionId": "question-1",
        "conversationContext": {
            "includedCompleteTurns": 1,
            "omittedCompleteTurns": 1,
        },
    }
    assert "recentConversation" not in payload


def test_chat_context_does_not_split_an_oversized_turn() -> None:
    context = assemble_retrospective_chat_context(
        message="继续",
        selected_question_id=None,
        conversation=(
            {"role": "user", "content": "历史问题"},
            {"role": "assistant", "content": "历史回答"},
        ),
        history_token_budget=1,
        token_counter=_fixed_tokens,
    )

    assert len(context.messages) == 1
    assert isinstance(context.messages[0], HumanMessage)
    assert context.included_complete_turns == 0
    assert context.omitted_complete_turns == 1
