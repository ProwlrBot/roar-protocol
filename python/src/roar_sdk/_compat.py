"""Compatibility helpers for Python version differences."""

from enum import Enum


class StrEnum(str, Enum):
    """Lightweight StrEnum backport for consistent typing on Python 3.10+."""

    def __str__(self) -> str:
        return self.value
