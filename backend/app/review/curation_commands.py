from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.review.models import CurationSummary


CommandKind = Literal[
    "confirm", "reject", "rewrite", "resummarize", "clarify"
]


class StaleCurationSummaryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedCurationCommand:
    kind: CommandKind
    candidate_ids: tuple[str, ...] = ()
    feedback: str | None = None
    clarification: str = ""


class CurationCommandService:
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
