from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping


MAX_WINDOW_CHARACTERS = 24_000
WINDOW_OVERLAP_CHARACTERS = 1_000


@dataclass(frozen=True, slots=True)
class SourceWindow:
    ordinal: int
    source_start: int
    source_end: int
    body: str

    @property
    def work_key(self) -> str:
        return f"window:{self.source_start}:{self.source_end}"


def create_source_windows(
    body: str,
    *,
    window_size: int = MAX_WINDOW_CHARACTERS,
    overlap: int = WINDOW_OVERLAP_CHARACTERS,
) -> tuple[SourceWindow, ...]:
    if not body:
        return ()
    if window_size <= 0 or overlap < 0 or overlap >= window_size:
        raise ValueError("窗口大小或重叠范围无效")
    step = window_size - overlap
    windows: list[SourceWindow] = []
    start = 0
    while start < len(body):
        end = min(start + window_size, len(body))
        windows.append(
            SourceWindow(
                ordinal=len(windows) + 1,
                source_start=start,
                source_end=end,
                body=body[start:end],
            )
        )
        if end == len(body):
            break
        start += step
    return tuple(windows)


def reduce_cleanup_segments(
    window_outputs: Iterable[Iterable[Mapping[str, object]]],
) -> tuple[dict[str, object], ...]:
    collected: list[dict[str, object]] = []
    seen: set[tuple[int, int, str]] = set()
    for window in window_outputs:
        previous_end = -1
        for raw in window:
            item = dict(raw)
            start = int(_value(item, "sourceStart", "source_start"))
            end = int(_value(item, "sourceEnd", "source_end"))
            if start < previous_end or end <= start:
                raise ValueError("window segment offset regression")
            previous_end = end
            text = str(_value(item, "text", "body")).strip()
            fingerprint = (start, end, _normalize_text(text))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            item["sourceStart"] = start
            item["sourceEnd"] = end
            item["text"] = text
            collected.append(item)
    collected.sort(key=lambda item: (int(item["sourceStart"]), int(item["sourceEnd"])))
    for ordinal, item in enumerate(collected, start=1):
        item["ordinal"] = ordinal
    return tuple(collected)


def _value(item: Mapping[str, object], *names: str) -> object:
    for name in names:
        if name in item:
            return item[name]
    raise ValueError(f"missing cleanup segment field: {names[0]}")


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
