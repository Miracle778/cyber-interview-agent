from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.agents.context import AgentContext
from app.middleware.defaults import REVIEW_ROUND_BUDGET, build_default_middleware
from app.middleware.no_progress import NoProgressError, NoProgressMiddleware


class Projection:
    def __init__(self) -> None:
        self.progress = {}

    def observe_progress(self, context, fingerprint):
        key = (context.run_id, fingerprint)
        self.progress[key] = self.progress.get(key, 0) + 1
        return self.progress[key]

    def warning(self, *_args):
        return None

    def record_usage(self, *_args):
        return True

    def ensure_title(self, *_args):
        return True

    def mark_context_compacted(self, *_args):
        return True


class Policy(AgentMiddleware):
    pass


class Sink:
    @contextmanager
    def span(self, *_args, **_kwargs):
        yield SimpleNamespace(record_error=lambda _code: None)


def _context() -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=Path("/workspace"),
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )


@pytest.mark.asyncio
async def test_review_profile_is_long_lived_and_round_progress_aware() -> None:
    projection = Projection()
    stack = build_default_middleware(
        summary_model=GenericFakeChatModel(
            messages=iter([AIMessage(content="summary")])
        ),
        projection=projection,
        policy=Policy(),
        observability=Sink(),
        interrupt_on={},
        budget_profile=REVIEW_ROUND_BUDGET,
    )
    model_limit = next(
        item for item in stack if isinstance(item, ModelCallLimitMiddleware)
    )
    no_progress = next(
        item for item in stack if isinstance(item, NoProgressMiddleware)
    )
    state = {"messages": [AIMessage(content="回答评价完成")]}

    assert model_limit.thread_limit >= 100
    for ordinal in range(1, 11):
        context = replace(
            _context(),
            progress_scope=("round-1", str(ordinal), f"input-{ordinal}"),
        )
        await no_progress.aafter_model(
            state, SimpleNamespace(context=context)
        )

    last_context = replace(
        _context(), progress_scope=("round-1", "10", "input-10")
    )
    await no_progress.aafter_model(
        state, SimpleNamespace(context=last_context)
    )
    with pytest.raises(NoProgressError):
        await no_progress.aafter_model(
            state, SimpleNamespace(context=last_context)
        )
