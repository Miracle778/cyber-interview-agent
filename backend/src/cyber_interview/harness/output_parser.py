import json
from dataclasses import dataclass

from pydantic import ValidationError

from cyber_interview.domain.errors import ErrorCategory, OutputError
from cyber_interview.domain.profile import ProfileVersion


@dataclass(frozen=True)
class FinalOutputResult:
    profile: ProfileVersion | None = None
    error: OutputError | None = None


class FinalOutputParser:
    """Accumulated delta text -> extracted JSON -> FinalOutputResult."""

    def parse(self, full_text: str, *, finish_reason: str | None) -> FinalOutputResult:
        extracted = self._extract_json(full_text)
        if extracted is None:
            return FinalOutputResult(
                error=OutputError(
                    category=ErrorCategory.MODEL,
                    safe_message="模型输出无法解析为 JSON",
                    finish_reason=finish_reason,
                )
            )
        try:
            profile = ProfileVersion.model_validate_json(extracted)
        except ValidationError:
            return FinalOutputResult(
                error=OutputError(
                    category=ErrorCategory.POLICY,
                    safe_message="schema 不合法",
                    finish_reason=finish_reason,
                )
            )
        return FinalOutputResult(profile=profile)

    def _extract_json(self, text: str) -> str | None:
        value = text.strip()
        if value.startswith("```"):
            lines = value.splitlines()
            if len(lines) >= 2:
                value = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        start = value.find("{")
        end = value.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        candidate = value[start : end + 1]
        try:
            json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return candidate
