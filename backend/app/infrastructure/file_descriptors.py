from __future__ import annotations

import os


def binary_open_flags(flags: int) -> int:
    """Return low-level open flags that preserve bytes on every platform."""
    return flags | getattr(os, "O_BINARY", 0)
