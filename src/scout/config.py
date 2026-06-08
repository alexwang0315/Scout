"""Configuration scaffold for Scout AI OS."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScoutAiOsConfig:
    """Minimal Scout AI OS runtime configuration."""

    data_dir: Path = Path(".scout-ai-os")


__all__ = ["ScoutAiOsConfig"]
