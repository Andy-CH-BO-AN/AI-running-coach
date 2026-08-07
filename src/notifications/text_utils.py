"""Shared text measurements for LINE message formatting and transport."""
from __future__ import annotations


def utf16_length(text: str) -> int:
    """Return text length in UTF-16 code units, matching LINE limits."""
    return len(text.encode("utf-16-le")) // 2
