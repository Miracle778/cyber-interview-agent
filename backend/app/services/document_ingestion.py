from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pypdf import PdfReader

from app.schemas.review import ReviewQuestion


ExtractionCode = Literal[
    "usable",
    "low_signal",
    "no_extractable_text",
    "unsupported_encoding",
    "parse_failed",
]


@dataclass(frozen=True, slots=True)
class TextExtractionResult:
    text: str
    code: ExtractionCode


def extract_text(path: Path) -> str:
    """Compatibility wrapper for callers that only need extracted text."""
    return extract_text_result(path).text


def extract_text_result(path: Path) -> TextExtractionResult:
    """Classify supported local text extraction without exposing parser errors."""
    if path.suffix.lower() == ".pdf":
        try:
            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except OSError:
            raise
        except Exception:
            return TextExtractionResult(text="", code="parse_failed")
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return TextExtractionResult(text="", code="unsupported_encoding")

    if not text.strip():
        return TextExtractionResult(text="", code="no_extractable_text")
    return TextExtractionResult(
        text=text,
        code="low_signal" if _is_low_signal(text) else "usable",
    )


def _is_low_signal(text: str) -> bool:
    meaningful = "".join(character for character in text if not character.isspace())
    if len(meaningful) < 24:
        return True
    return len(set(meaningful)) == 1


def create_question_draft(text: str) -> ReviewQuestion:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "未命名问题")
    return ReviewQuestion(
        id=f"q_{uuid4().hex[:12]}",
        title=first_line[:60],
        questionText=first_line,
        referenceAnswer=text[:1200],
        topics=["uncategorized"],
        difficulty="medium",
        keyPoints=[first_line[:80]],
        followUps=[],
        mastery="unknown",
    )
