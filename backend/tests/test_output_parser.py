import json

from cyber_interview.domain.errors import ErrorCategory
from cyber_interview.harness.output_parser import FinalOutputParser


def test_legal_json_returns_profile():
    text = json.dumps(
        {
            "schema_name": "profile",
            "schema_version": 1,
            "facts": [{"claim": "三年 Python", "evidence_ref": None}],
        }
    )
    result = FinalOutputParser().parse(text, finish_reason="stop")
    assert result.profile is not None
    assert result.error is None
    assert result.profile.facts[0].claim == "三年 Python"


def test_legal_json_with_markdown_fence():
    text = (
        "```json\n"
        + json.dumps(
            {
                "schema_name": "profile",
                "schema_version": 1,
                "facts": [{"claim": "x", "evidence_ref": None}],
            }
        )
        + "\n```"
    )
    result = FinalOutputParser().parse(text, finish_reason="stop")
    assert result.profile is not None


def test_illegal_json_returns_error_model():
    result = FinalOutputParser().parse("not json at all", finish_reason="stop")
    assert result.profile is None
    assert result.error.category is ErrorCategory.MODEL


def test_truncated_output_returns_error():
    text = '{"schema_name": "profile", "facts": [{"claim": "x"'
    result = FinalOutputParser().parse(text, finish_reason="length")
    assert result.profile is None
    assert result.error.finish_reason == "length"


def test_schema_invalid_returns_error_policy():
    text = json.dumps({"schema_name": "profile", "schema_version": 1, "facts": []})
    result = FinalOutputParser().parse(text, finish_reason="stop")
    assert result.profile is None
    assert result.error.category is ErrorCategory.POLICY
