from __future__ import annotations

from langchain.agents.middleware import SummarizationMiddleware


class ProjectingSummarizationMiddleware(SummarizationMiddleware):
    """Use official compaction and project only a content-free product indicator."""

    def __init__(self, *args, projection, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._projection = projection

    async def abefore_model(self, state, runtime):
        update = await super().abefore_model(state, runtime)
        if update is None:
            return None
        try:
            self._projection.mark_context_compacted(runtime.context)
        except Exception:
            self._projection.warning(runtime.context, "summary_projection_failed")
        return update
