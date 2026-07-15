from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.agents.curation_intent import CandidateSelector, CurationIntentPlan

from app.review.models import CurationSummary


CommandKind = Literal[
    "confirm", "reject", "rewrite", "mixed", "resummarize", "clarify"
]


class StaleCurationSummaryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedCurationCommand:
    kind: CommandKind
    candidate_ids: tuple[str, ...] = ()
    feedback: str | None = None
    clarification: str = ""
    rewrite_candidate_ids: tuple[str, ...] = ()


class CurationCommandService:
    def resolve_intent(
        self,
        *,
        intent: CurationIntentPlan,
        summary: CurationSummary,
        candidates: tuple[dict[str, Any], ...],
        current_summary_version: int,
        expected_summary_version: int,
    ) -> ParsedCurationCommand:
        if current_summary_version != expected_summary_version:
            raise StaleCurationSummaryError("curation summary changed before command resolution")
        if intent.clarification.strip():
            return ParsedCurationCommand(kind="clarify", clarification=intent.clarification.strip())
        inspect = self._resolve_selector(intent.inspect, summary, candidates)
        if inspect:
            return ParsedCurationCommand(
                kind="clarify",
                candidate_ids=inspect,
                clarification=self._candidate_detail_response(
                    inspect, candidates
                ),
            )
        if intent.response.strip():
            return ParsedCurationCommand(
                kind="clarify", clarification=intent.response.strip()
            )
        publish = self._resolve_selector(intent.publish, summary, candidates)
        reject = self._resolve_selector(intent.reject, summary, candidates)
        rewrite = self._resolve_selector(intent.regenerate, summary, candidates)
        if publish and rewrite:
            return ParsedCurationCommand(kind="mixed", candidate_ids=publish, rewrite_candidate_ids=rewrite, feedback=intent.feedback.strip() or None)
        if publish:
            return ParsedCurationCommand(kind="confirm", candidate_ids=publish)
        if reject:
            return ParsedCurationCommand(kind="reject", candidate_ids=reject)
        if rewrite:
            return ParsedCurationCommand(kind="rewrite", candidate_ids=rewrite, feedback=intent.feedback.strip() or None)
        if intent.resummarize:
            return ParsedCurationCommand(kind="resummarize")
        return ParsedCurationCommand(kind="clarify", clarification="我还不能确定要处理哪些题目，请再说明要发布、拒绝还是按备注重新生成。")

    @staticmethod
    def _candidate_detail_response(
        candidate_ids: tuple[str, ...],
        candidates: tuple[dict[str, Any], ...],
    ) -> str:
        by_id = {
            CurationCommandService._candidate_identifier(item): item
            for item in candidates
        }
        sections = []
        for candidate_id in candidate_ids:
            candidate = by_id[candidate_id]
            question = candidate.get("question") or {}
            key_points = question.get("key_points") or []
            follow_ups = question.get("follow_ups") or []
            lines = [
                f"第 {candidate['ordinal']} 题：{candidate['title']}",
                "",
                "题目：",
                str(question.get("question_text") or "暂无题干"),
                "",
                "参考答案：",
                str(question.get("reference_answer") or "暂无参考答案"),
                "",
                "关键点：",
                *(
                    [
                        f"{index}. {point}"
                        for index, point in enumerate(key_points, 1)
                    ]
                    if key_points
                    else ["暂无关键点"]
                ),
            ]
            if follow_ups:
                lines.extend(
                    [
                        "",
                        "必要追问：",
                        *[
                            f"{index}. {follow_up}"
                            for index, follow_up in enumerate(follow_ups, 1)
                        ],
                    ]
                )
            sections.append("\n".join(lines))
        return "\n\n".join(sections)

    def _resolve_selector(self, selector: CandidateSelector, summary: CurationSummary, candidates: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
        if selector.scope == "none":
            return ()
        by_id = {
            self._candidate_identifier(item): item for item in candidates
        }
        if selector.scope == "explicit":
            return self._resolve_ordinals(summary, tuple(selector.ordinals))
        identifiers = []
        for item in summary.items:
            candidate_id = str(item["candidateId"])
            candidate = by_id.get(candidate_id, {})
            if selector.scope == "recommended" and item.get("recommendation") != "recommend_confirm":
                continue
            note = str(
                candidate.get("review_note")
                or candidate.get("reviewNote")
                or ""
            ).strip()
            if selector.scope == "noted" and not note:
                continue
            if selector.scope == "unnoted" and note:
                continue
            identifiers.append(candidate_id)
        return tuple(identifiers)

    @staticmethod
    def _candidate_identifier(candidate: dict[str, Any]) -> str:
        identifier = candidate.get("id") or candidate.get("candidateId")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("candidate resource has no stable identifier")
        return identifier
    def parse(
        self,
        *,
        text: str,
        summary: CurationSummary,
        current_summary_version: int,
        expected_summary_version: int,
    ) -> ParsedCurationCommand:
        if current_summary_version != expected_summary_version:
            raise StaleCurationSummaryError(
                "curation summary changed before command resolution"
            )
        clean = text.strip()
        if clean in {"重新总结", "重新汇总"}:
            return ParsedCurationCommand(kind="resummarize")
        if re.fullmatch(r"确认(?:所有|全部)推荐题", clean):
            identifiers = tuple(
                str(item["candidateId"])
                for item in summary.items
                if item.get("recommendation") == "recommend_confirm"
            )
            return self._targets("confirm", identifiers)

        rewrite = re.fullmatch(
            r"重写第?\s*(\d+)\s*题?\s*[:：]\s*(.+)", clean
        )
        if rewrite:
            identifiers = self._resolve_ordinals(
                summary, (int(rewrite.group(1)),)
            )
            return ParsedCurationCommand(
                kind="rewrite",
                candidate_ids=identifiers,
                feedback=rewrite.group(2).strip(),
            )

        for prefix, kind in (("确认", "confirm"), ("拒绝", "reject")):
            if not clean.startswith(prefix):
                continue
            ordinal_text = clean[len(prefix) :].strip()
            ordinal_text = re.sub(r"^第\s*", "", ordinal_text)
            ordinal_text = re.sub(r"\s*题$", "", ordinal_text)
            if not re.fullmatch(r"\d+(?:\s*[、,，]\s*\d+)*", ordinal_text):
                break
            ordinals = tuple(
                int(value)
                for value in re.split(r"\s*[、,，]\s*", ordinal_text)
            )
            return self._targets(
                kind, self._resolve_ordinals(summary, ordinals)
            )

        return ParsedCurationCommand(
            kind="clarify",
            clarification=(
                "请明确回复“确认全部推荐题”“确认第 1、3 题”"
                "“拒绝第 2 题”或“重写第 4 题：修改要求”。"
            ),
        )

    @staticmethod
    def _resolve_ordinals(
        summary: CurationSummary, ordinals: tuple[int, ...]
    ) -> tuple[str, ...]:
        by_ordinal = {
            int(item["ordinal"]): str(item["candidateId"])
            for item in summary.items
        }
        try:
            return tuple(dict.fromkeys(by_ordinal[value] for value in ordinals))
        except KeyError as error:
            raise ValueError(f"unknown curation summary ordinal: {error.args[0]}")

    @staticmethod
    def _targets(
        kind: Literal["confirm", "reject"], identifiers: tuple[str, ...]
    ) -> ParsedCurationCommand:
        if not identifiers:
            return ParsedCurationCommand(
                kind="clarify",
                clarification="当前总结中没有符合该命令的题目，请指定题号。",
            )
        return ParsedCurationCommand(kind=kind, candidate_ids=identifiers)
