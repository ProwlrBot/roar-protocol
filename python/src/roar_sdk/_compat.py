# Python 3.10 compatibility shim for StrEnum (added in 3.11)
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Backport of Python 3.11 StrEnum for Python 3.10."""

        def __str__(self) -> str:
            return self.value
