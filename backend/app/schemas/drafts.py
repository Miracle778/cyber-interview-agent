from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class DraftModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class KnowledgeDraftResource(DraftModel):
    id: str
    workspace_id: str
    session_id: str | None
    execution_id: str | None = Field(validation_alias="run_id")
    agent_type: str | None
    domain: str
    document_type: str
    document_id: str
    title: str
    markdown: str
    content_path: str
    source_refs: tuple[str, ...]
    relation_refs: tuple[str, ...]
    status: str
    version: int
    content_hash: str
    created_at: str
    updated_at: str
    publication: "PublicationSummaryResource | None" = None


class PublicationSummaryResource(DraftModel):
    state: str
    target_path: str
    error_code: str | None


class KnowledgeSourceResource(DraftModel):
    id: str
    workspace_id: str
    original_filename: str
    stored_path: str
    content_type: str
    size_bytes: int
    created_at: str
    draft_id: str | None
    deleted_at: str | None = None


class UploadSourceResource(DraftModel):
    source: KnowledgeSourceResource


class UpdateKnowledgeDraftRequest(DraftModel):
    version: int = Field(ge=1)
    title: str | None = None
    markdown: str


class PublishDraftExecutionResource(DraftModel):
    session_id: str
    execution_id: str
    status: str
