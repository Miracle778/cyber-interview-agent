from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.interview_retrospective_contracts import (
    HistoricalSearchPlanOutput,
    HistoricalSearchReportOutput,
)


def test_history_search_plan_is_semantic_and_bounded() -> None:
    plan = HistoricalSearchPlanOutput.model_validate(
        {
            "searchTerms": ["数字签名", "PKI", "HSM"],
            "projectAliases": ["签名云服务"],
            "intentSummary": "查找历次数字签名项目问题",
        }
    )
    assert plan.search_terms == ["数字签名", "PKI", "HSM"]
    with pytest.raises(ValidationError):
        HistoricalSearchPlanOutput.model_validate(
            {"searchTerms": [f"term-{index}" for index in range(13)]}
        )


def test_history_report_rejects_unbounded_extra_fields() -> None:
    with pytest.raises(ValidationError):
        HistoricalSearchReportOutput.model_validate(
            {
                "title": "数字签名专项复盘",
                "markdown": "# 报告",
                "citationQuestionIds": ["question-1"],
                "workspaceId": "should-not-be-model-owned",
            }
        )
