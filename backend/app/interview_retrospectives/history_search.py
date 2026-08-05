from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.interview_retrospectives.models import (
    RetrospectiveSearchResultRecord,
    RetrospectiveSearchSetRecord,
)
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository


_STOP_TERMS = frozenset(
    {
        "之前",
        "所有",
        "关于",
        "问题",
        "面试",
        "过程",
        "帮我",
        "找一下",
        "一下",
        "项目",
        "哪些",
        "什么",
        "总结",
    }
)
_TECH_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9_.+#/-]{1,31}")
_HAN_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")


@dataclass(frozen=True, slots=True)
class RetrospectiveSearchFilters:
    job_target_id: str | None = None
    company: str | None = None
    role: str | None = None
    round_label: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    origins: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "jobTargetId": self.job_target_id,
            "company": self.company,
            "role": self.role,
            "roundLabel": self.round_label,
            "dateFrom": self.date_from,
            "dateTo": self.date_to,
            "origins": list(self.origins),
        }


@dataclass(frozen=True, slots=True)
class RetrospectiveSearchPlan:
    terms: tuple[str, ...]
    project_aliases: tuple[str, ...] = ()

    @classmethod
    def from_query(cls, query_text: str) -> "RetrospectiveSearchPlan":
        return cls(terms=_fallback_terms(query_text))

    def to_dict(self) -> dict[str, object]:
        return {
            "terms": list(self.terms),
            "projectAliases": list(self.project_aliases),
        }


@dataclass(frozen=True, slots=True)
class HistoricalSearchOutcome:
    search_set: RetrospectiveSearchSetRecord
    items: tuple[RetrospectiveSearchResultRecord, ...]


class HistoricalSearchService:
    def __init__(self, repository: InterviewRetrospectiveRepository) -> None:
        self.repository = repository

    def search(
        self,
        *,
        workspace_id: str,
        query_text: str,
        plan: RetrospectiveSearchPlan | None = None,
        filters: RetrospectiveSearchFilters | None = None,
        session_id: str | None = None,
        execution_id: str | None = None,
    ) -> HistoricalSearchOutcome:
        normalized_query = query_text.strip()
        if not normalized_query:
            raise ValueError("历史检索问题不能为空")
        resolved_plan = plan or RetrospectiveSearchPlan.from_query(normalized_query)
        resolved_filters = filters or RetrospectiveSearchFilters()
        search_set = self.repository.create_search_set(
            workspace_id=workspace_id,
            query_text=normalized_query,
            filters=resolved_filters.to_dict(),
            search_plan=resolved_plan.to_dict(),
            session_id=session_id,
            execution_id=execution_id,
            status="searching",
        )
        return self.search_existing(
            search_set_id=search_set.id,
            plan=resolved_plan,
            filters=resolved_filters,
        )

    def search_existing(
        self,
        *,
        search_set_id: str,
        plan: RetrospectiveSearchPlan,
        filters: RetrospectiveSearchFilters,
    ) -> HistoricalSearchOutcome:
        search_set = self.repository.get_search_set(search_set_id)
        terms = _unique_terms((*plan.terms, *plan.project_aliases))
        if not terms:
            terms = _fallback_terms(search_set.query_text)
        self.repository.update_search_set_plan(
            search_set_id,
            search_plan={**plan.to_dict(), "effectiveTerms": list(terms)},
        )
        ranked: list[dict[str, object]] = []
        for candidate in self.repository.list_history_search_candidates(
            workspace_id=search_set.workspace_id
        ):
            if not _matches_filters(candidate, filters):
                continue
            score, matched_terms = _score(candidate, terms)
            if score <= 0:
                continue
            ranked.append(
                {
                    "retrospective_id": candidate["retrospective_id"],
                    "question_unit_id": candidate["question_unit_id"],
                    "question_analysis_id": candidate["question_analysis_id"],
                    "score": score,
                    "matched_terms": matched_terms,
                    "source_metadata": {
                        "retrospectiveTitle": candidate["retrospective_title"],
                        "companyName": candidate["company_name"],
                        "roleName": candidate["role_name"],
                        "seniority": candidate["seniority"],
                        "roundLabel": candidate["round_label"],
                        "interviewDate": candidate["interview_date"],
                        "outcome": candidate["outcome"],
                    },
                    "question_snapshot": {
                        "ordinal": candidate["question_ordinal"],
                        "questionText": candidate["question_text"],
                        "questionKind": candidate["question_kind"],
                        "origin": candidate["origin"],
                        "confidence": candidate["question_confidence"],
                    },
                    "answer_excerpt": _bounded(
                        str(candidate["source_excerpt"]), 4_000
                    ),
                    "analysis_snapshot": {
                        "verdict": candidate["verdict"],
                        "strengths": candidate["strengths"],
                        "improvements": candidate["improvements"],
                        "omissions": candidate["omissions"],
                        "evidenceLevel": candidate["evidence_level"],
                        "confidence": candidate["analysis_confidence"],
                        "improvementOutline": candidate["improvement_outline"],
                        "suggestedAnswer": _bounded(
                            str(candidate["suggested_answer"]), 2_000
                        ),
                    },
                    "source_available": candidate["source_available"],
                    "_date": str(candidate["interview_date"] or ""),
                    "_ordinal": int(candidate["question_ordinal"]),
                }
            )
        ranked.sort(
            key=lambda item: (
                -float(item["score"]),
                -_date_number(str(item["_date"])),
                str(item["retrospective_id"]),
                int(item["_ordinal"]),
                str(item["question_unit_id"]),
            )
        )
        for item in ranked:
            item.pop("_date", None)
            item.pop("_ordinal", None)
        items = self.repository.replace_search_results(
            search_set_id, results=ranked
        )
        return HistoricalSearchOutcome(
            search_set=self.repository.get_search_set(search_set_id),
            items=items,
        )


def _matches_filters(
    item: dict[str, object], filters: RetrospectiveSearchFilters
) -> bool:
    if filters.job_target_id and item["job_target_id"] != filters.job_target_id:
        return False
    if filters.company and _normalize(filters.company) not in _normalize(
        str(item["company_name"] or "")
    ):
        return False
    if filters.role and _normalize(filters.role) not in _normalize(
        str(item["role_name"] or "")
    ):
        return False
    if filters.round_label and _normalize(filters.round_label) not in _normalize(
        str(item["round_label"] or "")
    ):
        return False
    date = str(item["interview_date"] or "")
    if filters.date_from and (not date or date < filters.date_from):
        return False
    if filters.date_to and (not date or date > filters.date_to):
        return False
    if filters.origins and item["origin"] not in filters.origins:
        return False
    return True


def _score(
    item: dict[str, object], terms: tuple[str, ...]
) -> tuple[float, tuple[str, ...]]:
    fields = (
        (str(item["question_text"]), 8.0),
        (
            " ".join(
                str(item[key] or "")
                for key in (
                    "retrospective_title",
                    "company_name",
                    "role_name",
                    "round_label",
                )
            ),
            6.0,
        ),
        (str(item["source_excerpt"]), 4.0),
        (
            " ".join(
                (
                    str(item["verdict"]),
                    str(item["strengths"]),
                    str(item["improvements"]),
                    str(item["omissions"]),
                    str(item["improvement_outline"]),
                    str(item["suggested_answer"]),
                )
            ),
            2.0,
        ),
    )
    score = 0.0
    matched: list[str] = []
    for term in terms:
        normalized_term = _normalize(term)
        if not normalized_term:
            continue
        term_score = sum(
            weight for value, weight in fields if normalized_term in _normalize(value)
        )
        if term_score:
            score += term_score + (2.0 if len(normalized_term) >= 4 else 0.0)
            matched.append(term)
    return score, tuple(matched)


def _fallback_terms(query_text: str) -> tuple[str, ...]:
    terms: list[str] = list(_TECH_TOKEN.findall(query_text))
    for run in _HAN_RUN.findall(query_text):
        reduced = run
        for stop in sorted(_STOP_TERMS, key=len, reverse=True):
            reduced = reduced.replace(stop, " ")
        terms.extend(part for part in reduced.split() if len(part) >= 2)
    return _unique_terms(terms)


def _unique_terms(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        normalized = _normalize(text)
        if not normalized or normalized in seen or normalized in _STOP_TERMS:
            continue
        seen.add(normalized)
        result.append(text)
        if len(result) >= 24:
            break
    return tuple(result)


def _normalize(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE).casefold()


def _bounded(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[:limit]}…"


def _date_number(value: str) -> int:
    digits = "".join(character for character in value if character.isdigit())[:8]
    return int(digits) if digits else 0
