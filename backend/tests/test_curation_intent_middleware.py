from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app.application.workspace_runtime import build_curation_intent_context
from app.middleware.no_progress import NoProgressError, NoProgressMiddleware


class Projection:
    def __init__(self) -> None:
        self.counts = Counter()

    def observe_progress(self, context, fingerprint):
        key = (context.run_id, fingerprint)
        self.counts[key] += 1
        return self.counts[key]

    def warning(self, context, code):
        return None


@pytest.mark.asyncio
async def test_independent_curation_commands_do_not_share_loop_fingerprint(
    tmp_path,
) -> None:
    middleware = NoProgressMiddleware(
        Projection(),
        warning_limit=2,
        hard_limit=3,
        include_context_scope=True,
    )
    state = {"messages": [AIMessage(content="查看候选题详情")]}

    for key in ("command-one", "command-two", "command-three"):
        context = build_curation_intent_context(
            workspace_id="w1",
            workspace_root=tmp_path,
            session_id="s1",
            run_id="existing-curation-run",
            idempotency_key=key,
            invocation_id=f"invocation-{key}",
        )
        await middleware.aafter_model(
            state, SimpleNamespace(context=context)
        )

    repeated = build_curation_intent_context(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="s1",
        run_id="existing-curation-run",
        idempotency_key="command-three",
        invocation_id="invocation-command-three",
    )
    retried_request = build_curation_intent_context(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="s1",
        run_id="existing-curation-run",
        idempotency_key="command-three",
        invocation_id="invocation-command-three-retry",
    )
    await middleware.aafter_model(
        state, SimpleNamespace(context=retried_request)
    )
    await middleware.aafter_model(state, SimpleNamespace(context=repeated))
    with pytest.raises(NoProgressError):
        await middleware.aafter_model(
            state, SimpleNamespace(context=repeated)
        )
