"""Safe, source-local preparation for question-curation discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.document_ingestion import extract_text_result


@dataclass(frozen=True, slots=True)
class CurationSourcePreparation:
    excerpts: tuple[tuple[str, str], ...]
    warnings: tuple[dict[str, str], ...]

    @property
    def has_usable_text(self) -> bool:
        return bool(self.excerpts)


def prepare_curation_sources(
    sources: tuple[tuple[str, Path], ...],
) -> CurationSourcePreparation:
    excerpts: list[tuple[str, str]] = []
    warnings: list[dict[str, str]] = []
    for source_id, path in sources:
        result = extract_text_result(path)
        if result.code in {"usable", "low_signal"}:
            excerpts.append((source_id, result.text))
        if result.code != "usable":
            warnings.append({"sourceId": source_id, "code": result.code})
    return CurationSourcePreparation(tuple(excerpts), tuple(warnings))
