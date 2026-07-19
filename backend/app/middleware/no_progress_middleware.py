from __future__ import annotations

import hashlib
import json
import re

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

from app.middleware.usage_projection_middleware import MiddlewareProjection


class NoProgressError(RuntimeError):
    code = "no_progress"

    def __init__(self) -> None:
        super().__init__(self.code)


class NoProgressMiddleware(AgentMiddleware):
    def __init__(
        self,
        projection: MiddlewareProjection,
        *,
        warning_limit: int = 2,
        hard_limit: int = 3,
        include_context_scope: bool = False,
    ) -> None:
        if warning_limit >= hard_limit:
            raise ValueError("warning_limit must be below hard_limit")
        self._projection = projection
        self.warning_limit = warning_limit
        self.hard_limit = hard_limit
        self.include_context_scope = include_context_scope

    async def aafter_model(self, state, runtime) -> None:
        message = next(
            (
                item
                for item in reversed(state.get("messages", ()))
                if isinstance(item, AIMessage)
            ),
            None,
        )
        if message is None:
            return None
        fingerprint = _fingerprint(
            message,
            context_scope=(
                getattr(runtime.context, "progress_scope", ())
                if self.include_context_scope
                else ()
            ),
        )
        try:
            count = self._projection.observe_progress(runtime.context, fingerprint)
        except Exception:
            self._projection.warning(runtime.context, "progress_projection_failed")
            return None
        if count >= self.hard_limit:
            raise NoProgressError()
        if count == self.warning_limit:
            self._projection.warning(runtime.context, "no_progress_warning")
        return None


def _fingerprint(
    message: AIMessage, *, context_scope: tuple[str, ...] = ()
) -> str:
    normalized_calls = [
        {"name": call.get("name"), "args": call.get("args", {})}
        for call in message.tool_calls
    ]
    body = {
        "content": re.sub(r"\s+", " ", message.text).strip().lower(),
        "tool_calls": normalized_calls,
        "context_scope": context_scope,
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
