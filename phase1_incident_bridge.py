from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

from phase1_phase2_adapter import (
    adapt_phase1_incident_package,
    load_phase1_incident_package,
    persist_phase1_adapter_output,
)
from phase2_brain_models import BrainNode
from phase2_brain_store import BrainFileStore


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Phase1IncidentBridgeResult:
    enabled: bool
    status: Literal["skipped", "succeeded", "failed"]
    attempted: bool = False
    incident_package_path: Path | None = None
    incident_id: str | None = None
    node_ids: tuple[str, ...] = ()
    written_paths: tuple[Path, ...] = ()
    skipped_reason: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    @property
    def skipped(self) -> bool:
        return self.status == "skipped"

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    @property
    def failed(self) -> bool:
        return self.status == "failed"


class Phase1IncidentBridge:
    def __init__(
        self,
        *,
        enabled: bool = False,
        brain_store_root: Path | str | None = None,
        mission_id: str | None = None,
    ):
        self.enabled = enabled
        self.brain_store_root = Path(brain_store_root) if brain_store_root is not None else None
        self.mission_id = mission_id

    def import_persisted_incident(self, incident_package_path: Path | str) -> Phase1IncidentBridgeResult:
        path = Path(incident_package_path)
        if not self.enabled:
            return Phase1IncidentBridgeResult(
                enabled=False,
                status="skipped",
                incident_package_path=path,
                skipped_reason="disabled",
            )
        if self.brain_store_root is None:
            return Phase1IncidentBridgeResult(
                enabled=True,
                status="skipped",
                incident_package_path=path,
                skipped_reason="missing_brain_store_root",
            )

        package = load_phase1_incident_package(path)
        output = adapt_phase1_incident_package(
            package,
            source_uri=path.as_posix(),
            mission_id=self.mission_id,
        )
        store = BrainFileStore(self.brain_store_root)
        written_paths = persist_phase1_adapter_output(store, output)
        return Phase1IncidentBridgeResult(
            enabled=True,
            status="succeeded",
            attempted=True,
            incident_package_path=path,
            incident_id=package.incident_id,
            node_ids=tuple(_node_ids(output.nodes)),
            written_paths=tuple(written_paths),
        )

    def try_import_persisted_incident(self, incident_package_path: Path | str) -> Phase1IncidentBridgeResult:
        try:
            return self.import_persisted_incident(incident_package_path)
        except Exception as exc:
            logger.warning(
                "Phase 1 incident bridge failed for %s: %s",
                incident_package_path,
                exc,
                exc_info=True,
            )
            return Phase1IncidentBridgeResult(
                enabled=self.enabled,
                status="failed",
                attempted=True,
                incident_package_path=Path(incident_package_path),
                skipped_reason=f"bridge_error:{type(exc).__name__}",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def try_import_persisted_incidents(
        self, incident_package_paths: Sequence[Path | str]
    ) -> tuple[Phase1IncidentBridgeResult, ...]:
        return tuple(self.try_import_persisted_incident(path) for path in incident_package_paths)


def _node_ids(nodes: list[BrainNode]) -> list[str]:
    return [node.id for node in nodes]


def phase1_incident_bridge_from_env(env: Mapping[str, str] | None = None) -> Phase1IncidentBridge | None:
    values = env if env is not None else os.environ
    enabled = _is_true_like(values.get("SCOUT_PHASE2_INCIDENT_BRIDGE"))
    if not enabled:
        return None

    store_root = values.get("SCOUT_PHASE2_BRAIN_STORE_ROOT")
    if store_root is None or not store_root.strip():
        logger.warning(
            "SCOUT_PHASE2_INCIDENT_BRIDGE is enabled but SCOUT_PHASE2_BRAIN_STORE_ROOT is missing; bridge disabled"
        )
        return None
    store_path = Path(store_root)
    if store_path.exists() and not store_path.is_dir():
        logger.warning(
            "SCOUT_PHASE2_INCIDENT_BRIDGE is enabled but SCOUT_PHASE2_BRAIN_STORE_ROOT is not a directory; bridge disabled"
        )
        return None

    return Phase1IncidentBridge(
        enabled=True,
        brain_store_root=store_path,
        mission_id=values.get("SCOUT_PHASE2_BRIDGE_MISSION_ID"),
    )


def _is_true_like(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}
