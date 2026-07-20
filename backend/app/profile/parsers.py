from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from app.profile.errors import (
    ProfileEncryptedDocument,
    ProfileNoExtractableText,
    ProfileParseError,
    ProfileUnsupportedFileType,
)

_PDF_EXT = ".pdf"
_DOCX_EXT = ".docx"
_MARKDOWN_EXTS = {".md", ".markdown"}
_TEXT_EXT = ".txt"


@dataclass(frozen=True, slots=True)
class ExtractedSegment:
    text: str
    locator: dict[str, int]


def parse_document(
    *, file_name: str, mime_type: str, content: bytes
) -> tuple[ExtractedSegment, ...]:
    """Parse uploaded material bytes into evidence-grounded segments.

    The locator identifies where each segment came from: ``{page}`` for PDF,
    ``{paragraph}`` for DOCX, ``{lineStart, lineEnd}`` for Markdown/text. Line
    endings are normalized in the extracted text; source bytes are never
    rewritten. Errors are redacted and use stable codes.
    """
    del mime_type  # dispatch by validated extension; never trust the browser media type
    extension = Path(file_name).suffix.lower()
    if extension == _PDF_EXT:
        return _parse_pdf(content)
    if extension == _DOCX_EXT:
        return _parse_docx(content)
    if extension in _MARKDOWN_EXTS or extension == _TEXT_EXT:
        return _parse_text(content)
    raise ProfileUnsupportedFileType("unsupported file type")


def _parse_pdf(content: bytes) -> tuple[ExtractedSegment, ...]:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as error:  # pragma: no cover - dependency guarded by lock
        raise ProfileParseError("pdf parser unavailable") from error

    try:
        reader = PdfReader(io.BytesIO(content))
    except PdfReadError as error:
        raise ProfileParseError("pdf could not be read") from error
    except Exception as error:
        raise ProfileParseError("pdf could not be read") from error

    if reader.is_encrypted:
        try:
            decrypted = reader.decrypt("")
        except Exception:
            decrypted = 0
        if not decrypted:
            raise ProfileEncryptedDocument("document is encrypted")

    segments: list[ExtractedSegment] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        cleaned = text.strip()
        if cleaned:
            segments.append(ExtractedSegment(text=cleaned, locator={"page": index}))

    if not segments:
        raise ProfileNoExtractableText(
            "pdf has no extractable text (scanned image resumes require OCR, "
            "which is outside the R3 first milestone"
        )
    return tuple(segments)


def _parse_docx(content: bytes) -> tuple[ExtractedSegment, ...]:
    try:
        from docx import Document
    except ImportError as error:  # pragma: no cover - dependency guarded by lock
        raise ProfileParseError("docx parser unavailable") from error

    try:
        document = Document(io.BytesIO(content))
    except Exception as error:
        raise ProfileParseError("docx could not be read") from error

    segments: list[ExtractedSegment] = []
    for index, paragraph in enumerate(document.paragraphs, start=1):
        text = paragraph.text.strip()
        if text:
            segments.append(
                ExtractedSegment(text=text, locator={"paragraph": index})
            )
    return tuple(segments)


def _parse_text(content: bytes) -> tuple[ExtractedSegment, ...]:
    try:
        raw = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProfileParseError("text must be utf-8 encoded") from error
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    segments: list[ExtractedSegment] = []
    start: int | None = None
    buffer: list[str] = []
    for index, line in enumerate(lines, start=1):
        if line.strip():
            if start is None:
                start = index
            buffer.append(line)
        else:
            if buffer:
                segments.append(
                    ExtractedSegment(
                        text="\n".join(buffer),
                        locator={"lineStart": start, "lineEnd": index - 1},
                    )
                )
                start = None
                buffer = []
    if buffer:
        segments.append(
            ExtractedSegment(
                text="\n".join(buffer),
                locator={"lineStart": start, "lineEnd": len(lines)},
            )
        )
    return tuple(segments)
