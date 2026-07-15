from __future__ import annotations

from langchain.agents.middleware import SummarizationMiddleware

from app.middleware.usage import ContextUsageProjection


class ProjectingSummarizationMiddleware(SummarizationMiddleware):
    """Use official compaction and project only a content-free product indicator."""

    def __init__(self, *args, projection, threshold_tokens: int, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._projection = projection
        self.threshold_tokens = threshold_tokens

    async def abefore_model(self, state, runtime):
        current_tokens = self.token_counter(state.get("messages", ()))
        try:
            self._projection.record_context_usage(
                runtime.context,
                ContextUsageProjection(
                    current_tokens=current_tokens,
                    threshold_tokens=self.threshold_tokens,
                ),
            )
        except Exception:
            self._projection.warning(runtime.context, "context_usage_projection_failed")
        update = await super().abefore_model(state, runtime)
        if update is None:
            return None
        try:
            self._projection.mark_context_compacted(runtime.context)
        except Exception:
            self._projection.warning(runtime.context, "summary_projection_failed")
        return update
