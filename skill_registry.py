from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import yaml

from skill_registry_models import SkillManifest


class DuplicateSkillManifestError(ValueError):
    pass


class SkillRegistry:
    def __init__(self, manifests: Iterable[SkillManifest]):
        self._manifests: dict[str, SkillManifest] = {}
        for manifest in manifests:
            if manifest.id in self._manifests:
                raise DuplicateSkillManifestError(f"duplicate skill manifest id: {manifest.id}")
            self._manifests[manifest.id] = manifest
        self._validate_preflight_dependencies()

    def __iter__(self) -> Iterator[SkillManifest]:
        return iter(self.list())

    def get(self, skill_id: str) -> SkillManifest:
        return self._manifests[skill_id]

    def list(self) -> list[SkillManifest]:
        return [self._manifests[skill_id] for skill_id in self.skill_ids()]

    def skill_ids(self) -> list[str]:
        return sorted(self._manifests)

    def _validate_preflight_dependencies(self) -> None:
        known_skill_ids = set(self._manifests)
        missing: dict[str, list[str]] = {}
        for manifest in self._manifests.values():
            missing_refs = [
                skill_id
                for skill_id in manifest.preflight.required_skill_ids
                if skill_id not in known_skill_ids
            ]
            if missing_refs:
                missing[manifest.id] = missing_refs

        if missing:
            details = "; ".join(
                f"{skill_id} requires {', '.join(refs)}"
                for skill_id, refs in sorted(missing.items())
            )
            raise ValueError(f"skill manifest preflight dependencies are missing: {details}")


def load_skill_registry(directory: Path | str) -> SkillRegistry:
    root = Path(directory)
    manifests = [load_skill_manifest(path) for path in sorted(root.glob("*.yaml"))]
    return SkillRegistry(manifests)


def load_skill_manifest(path: Path | str) -> SkillManifest:
    manifest_path = Path(path)
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{manifest_path} must contain a YAML mapping")
    return SkillManifest.model_validate(_string_keyed_mapping(payload))


def _string_keyed_mapping(payload: dict[Any, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items()}
