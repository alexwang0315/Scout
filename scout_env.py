from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping


DEFAULT_PERSISTENT_SCOUT_ENV = Path.home() / ".scout" / ".env"


@dataclass(frozen=True)
class ScoutEnvLoadResult:
    loaded_files: tuple[str, ...]
    loaded_keys: tuple[str, ...]
    credential_values_exposed: bool = False


def load_scout_env_files(
    *,
    repo_root: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
    persistent_env_file: Path | None = None,
    override: bool = False,
) -> ScoutEnvLoadResult:
    """Load repo-local and persistent Scout env files without exposing values."""

    target = environ if environ is not None else os.environ
    root = Path(repo_root).expanduser() if repo_root else Path(__file__).resolve().parent
    persistent_path = _persistent_env_path(target, persistent_env_file)
    candidates = (root / ".env", persistent_path)

    loaded_files: list[str] = []
    loaded_keys: list[str] = []
    for candidate in candidates:
        loaded = _load_env_file(candidate, target=target, override=override)
        if loaded:
            loaded_files.append(str(candidate))
            loaded_keys.extend(loaded)

    return ScoutEnvLoadResult(
        loaded_files=tuple(dict.fromkeys(loaded_files)),
        loaded_keys=tuple(dict.fromkeys(loaded_keys)),
    )


def _persistent_env_path(
    environ: Mapping[str, str],
    persistent_env_file: Path | None,
) -> Path:
    if persistent_env_file is not None:
        return Path(persistent_env_file).expanduser()
    configured = environ.get("SCOUT_PERSISTENT_ENV_FILE")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_PERSISTENT_SCOUT_ENV


def _load_env_file(
    path: Path,
    *,
    target: MutableMapping[str, str],
    override: bool,
) -> list[str]:
    env_path = Path(path).expanduser()
    if not env_path.exists():
        return []

    loaded: list[str] = []
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if not override and target.get(key):
            continue
        target[key] = value
        loaded.append(key)
    return loaded


def _parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    if line.startswith("export "):
        line = line.removeprefix("export ").strip()
    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, _strip_env_quotes(value.strip())


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
