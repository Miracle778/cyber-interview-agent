from pydantic import BaseModel, Field, field_validator


class ProfileFact(BaseModel):
    claim: str = Field(min_length=1)
    evidence_ref: str | None = None

    @field_validator("claim")
    @classmethod
    def claim_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim must not be blank")
        return value


class ProfileVersion(BaseModel):
    """Profile authority JSON schema (spec §5)."""

    schema_name: str = "profile"
    schema_version: int = 1
    facts: list[ProfileFact] = Field(min_length=1, max_length=3)
