from __future__ import annotations

import re


_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")


def redact_profile_text(text: str) -> tuple[str, bool]:
    """Return the exact text variant that may be sent to a model."""
    redacted = _EMAIL.sub("[email redacted]", text)
    redacted = _PHONE.sub("[phone redacted]", redacted)
    return redacted, redacted != text
