from app.tools.file_tools import (
    ReadTextInput,
    ReadTextOutput,
    WriteDraftInput,
    WriteDraftOutput,
    diagnostic_read,
    read_active_knowledge,
    read_source,
    write_review_draft,
)
from app.tools.registry import ToolDefinition, ToolRegistry


def create_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definition in (
        ToolDefinition(
            name="read_source",
            input_model=ReadTextInput,
            output_model=ReadTextOutput,
            risk_level="low",
            required_scope="review.sources",
            audit_policy="metadata_only",
            handler=read_source,
        ),
        ToolDefinition(
            name="read_active_knowledge",
            input_model=ReadTextInput,
            output_model=ReadTextOutput,
            risk_level="low",
            required_scope="knowledge.active",
            audit_policy="metadata_only",
            handler=read_active_knowledge,
        ),
        ToolDefinition(
            name="write_review_draft",
            input_model=WriteDraftInput,
            output_model=WriteDraftOutput,
            risk_level="medium",
            required_scope="review.drafts",
            audit_policy="metadata_only",
            handler=write_review_draft,
        ),
        ToolDefinition(
            name="diagnostic_read",
            input_model=ReadTextInput,
            output_model=ReadTextOutput,
            risk_level="low",
            required_scope="diagnostics.security",
            audit_policy="metadata_only",
            handler=diagnostic_read,
        ),
    ):
        registry.register(definition)
    return registry
