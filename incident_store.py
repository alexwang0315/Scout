from __future__ import annotations

import json
from pathlib import Path

from safety_models import IncidentPackage


class IncidentStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, package: IncidentPackage) -> Path:
        path = self.path_for(package.incident_id)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(package.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(path)
        return path

    def load(self, incident_id: str) -> IncidentPackage:
        payload = json.loads(self.path_for(incident_id).read_text(encoding="utf-8"))
        return IncidentPackage.model_validate(payload)

    def exists(self, incident_id: str) -> bool:
        return self.path_for(incident_id).exists()

    def list_ids(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.json"))

    def path_for(self, incident_id: str) -> Path:
        return self.root / f"{incident_id}.json"
