from __future__ import annotations

import re

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.middleware.usage_projection_middleware import MiddlewareProjection


class SessionTitleMiddleware(AgentMiddleware):
    """Offer a title candidate once; the projection owns the user-title CAS."""

    def __init__(self, projection: MiddlewareProjection, *, max_length: int = 60) -> None:
        self._projection = projection
        self._max_length = max_length
        self._seen_sessions: set[str] = set()

    async def aafter_agent(self, state, runtime) -> None:
        session_id = runtime.context.session_id
        if session_id in self._seen_sessions:
            return None
        first_human = next(
            (
                item
                for item in state.get("messages", ())
                if isinstance(item, HumanMessage) and item.text.strip()
            ),
            None,
        )
        if first_human is None:
            return None
        candidate = re.sub(r"\s+", " ", first_human.text).strip()[: self._max_length]
        try:
            self._projection.ensure_title(runtime.context, candidate)
        except Exception:
            self._projection.warning(runtime.context, "session_title_projection_failed")
            return None
        self._seen_sessions.add(session_id)
        return None

