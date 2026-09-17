"""Small Pydantic AI result compatibility helpers without agent imports."""

from __future__ import annotations

from typing import Any


def pydantic_result_output(result: Any) -> Any:
    """Return the structured output across supported Pydantic AI versions."""

    return getattr(result, "output", getattr(result, "data", result))
