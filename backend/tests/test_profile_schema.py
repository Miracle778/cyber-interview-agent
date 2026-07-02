import pytest
from pydantic import ValidationError

from cyber_interview.domain.profile import ProfileVersion


def test_valid_profile_with_one_fact():
    pv = ProfileVersion.model_validate(
        {
            "schema_name": "profile",
            "schema_version": 1,
            "facts": [{"claim": "三年 Python", "evidence_ref": None}],
        }
    )
    assert pv.facts[0].claim == "三年 Python"
    assert pv.facts[0].evidence_ref is None


def test_rejects_empty_facts():
    with pytest.raises(ValidationError):
        ProfileVersion.model_validate({"schema_name": "profile", "schema_version": 1, "facts": []})


def test_rejects_more_than_three_facts():
    facts = [{"claim": f"c{i}", "evidence_ref": None} for i in range(4)]
    with pytest.raises(ValidationError):
        ProfileVersion.model_validate(
            {"schema_name": "profile", "schema_version": 1, "facts": facts}
        )


def test_rejects_empty_claim():
    with pytest.raises(ValidationError):
        ProfileVersion.model_validate(
            {
                "schema_name": "profile",
                "schema_version": 1,
                "facts": [{"claim": "  ", "evidence_ref": None}],
            }
        )
