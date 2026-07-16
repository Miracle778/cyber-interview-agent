from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CandidateSelector(BaseModel):
    scope: Literal[
        "none", "explicit", "recommended", "noted", "unnoted", "all"
    ] = "none"
    ordinals: list[int] = Field(default_factory=list)


class CurationCommandPlan(BaseModel):
    publish: CandidateSelector = Field(default_factory=CandidateSelector)
    reject: CandidateSelector = Field(default_factory=CandidateSelector)
    regenerate: CandidateSelector = Field(default_factory=CandidateSelector)
    inspect: CandidateSelector = Field(default_factory=CandidateSelector)
    feedback: str = ""
    resummarize: bool = False
    clarification: str = ""


class CurationDialogueSummary(BaseModel):
    text: str = ""
    resource_refs: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_items: list[str] = Field(default_factory=list)
