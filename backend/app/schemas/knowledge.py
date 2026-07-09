from typing import Literal

from pydantic import BaseModel, Field

DocumentStatus = Literal["draft", "review_pending", "reviewed", "ingested", "stale", "archived"]
DocumentType = Literal["source", "question", "concept", "session_report", "mastery_report"]

class VaultDocument(BaseModel):
    id: str
    path: str
    title: str
    type: DocumentType
    status: DocumentStatus
    updated_at: str = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}
