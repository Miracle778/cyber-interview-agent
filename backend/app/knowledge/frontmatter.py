from __future__ import annotations

from typing import Literal

import frontmatter
from pydantic import BaseModel, ConfigDict, Field


DocumentType = Literal[
    "source",
    "question",
    "concept",
    "session_report",
    "mastery_report",
    "interview_retrospective",
]


class PublishedProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_type: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    model_id: str | None = None


class PublishedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: DocumentType
    title: str = Field(min_length=1)
    markdown: str = Field(min_length=1)
    source_refs: tuple[str, ...] = ()
    relation_refs: tuple[str, ...] = ()
    published_at: str = Field(min_length=1)
    provenance: PublishedProvenance


def render_published_document(document: PublishedDocument) -> str:
    post = frontmatter.Post(
        content=document.markdown.rstrip() + "\n",
        schema_version=1,
        id=document.id,
        type=document.type,
        status="ingested",
        title=document.title,
        source_refs=list(document.source_refs),
        relation_refs=list(document.relation_refs),
        ingestion={
            "confirmed_by_user": True,
            "published_at": document.published_at,
        },
        provenance=document.provenance.model_dump(exclude_none=True),
    )
    return frontmatter.dumps(post)
