from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from app.agents.context import AgentContext


def isolated_thread_config(
    config: dict[str, Any], context: AgentContext, namespace: str
) -> dict[str, Any]:
    """Preserve invocation options while isolating an Agent role checkpoint thread."""

    isolated = {
        key: value for key, value in config.items() if key != "configurable"
    }
    isolated["configurable"] = {
        "thread_id": f"{context.session_id}:{namespace}"
    }
    return isolated


def final_ai_text(result: dict[str, Any]) -> str:
    messages = result.get("messages", ())
    final = messages[-1] if messages else None
    return final.text.strip() if isinstance(final, AIMessage) else ""
