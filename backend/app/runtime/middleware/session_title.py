from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.runtime.middleware.types import BaseRuntimeMiddleware, MiddlewareLayer
from app.runtime.middleware.observability import NoopObservabilitySink, as_trace_context
from app.runtime.repository import RuntimeRepository


def normalize_title(value: str) -> str:
    return " ".join(value.replace("\n", " ").strip(" '\"").split())[:40]


class SessionTitleMiddleware(BaseRuntimeMiddleware):
    middleware_id = "session_title"
    layer = MiddlewareLayer.POST_PROCESSING
    order = 310

    def __init__(
        self,
        repository: RuntimeRepository,
        generate_title: Callable[[tuple[object, ...]], Awaitable[str]],
        *,
        publish_warning=lambda code: None,
        placeholders: frozenset[str] = frozenset({"新会话", "未命名会话"}),
        observability=None,
    ) -> None:
        self._repository = repository
        self._generate_title = generate_title
        self._publish_warning = publish_warning
        self._placeholders = placeholders
        self._observability = observability or NoopObservabilitySink()

    async def after_message(self, context, message) -> None:
        session = self._repository.get_session(context.session_id)
        if session.title not in self._placeholders:
            return
        messages = self._repository.list_messages(context.session_id)
        if not any(item.role == "user" for item in messages) or not any(
            item.role == "assistant" for item in messages
        ):
            return
        try:
            with self._observability.span(
                "middleware.session_title",
                context=as_trace_context(context),
                attributes={"cyber.trigger": "first_completed_exchange"},
            ) as span:
                title = normalize_title(await self._generate_title(messages))
                if title:
                    self._repository.compare_and_set_session_title(
                        context.session_id, expected=session.title, title=title
                    )
                span.set_attribute("cyber.status", "completed")
        except Exception:
            self._publish_warning("session_title_failed")
