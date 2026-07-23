from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal


ModelCall = Callable[..., tuple[str, dict[str, Any]]]
ContextualModelCall = Callable[..., tuple[str, dict[str, Any]]]


@dataclass(frozen=True)
class ScoutModelExecutionAdapter:
    """Bind one model implementation to explicit, auditable route metadata."""

    adapter_id: str
    profile: Literal["cloud", "local"]
    provider: str
    transport: str
    invoke: ModelCall
    invoke_with_context: ContextualModelCall | None = None
