from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.review import ReviewQuestion


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class DraftModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class KnowledgeDraftResource(DraftModel):
    id: str
    workspace_id: str
    session_id: str | None
    run_id: str | None
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


class UploadSourceResource(DraftModel):
    draft: KnowledgeDraftResource
    question: ReviewQuestion
