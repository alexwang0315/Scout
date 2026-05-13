from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from phase2_brain_models import BrainNode, SkillRunRecord
from phase2_brain_store import BrainFileStore
from phase2_writeback_policy import require_write_allowed
from skill_runtime import require_explicit_skill_run_writeback


def ingest_brain_node(
    store: BrainFileStore,
    node: BrainNode,
    *,
    automatic: bool,
    manual_write: bool = False,
    strict_artifact_refs: bool = False,
) -> Path:
    """Validate writeback policy and persist a Brain node unchanged."""

    _require_ingest_allowed(node, automatic=automatic, manual_write=manual_write)
    return store.write_node(node, strict_artifact_refs=strict_artifact_refs)


def ingest_brain_nodes(
    store: BrainFileStore,
    nodes: Iterable[BrainNode],
    *,
    automatic: bool,
    manual_write: bool = False,
    strict_artifact_refs: bool = False,
) -> list[Path]:
    paths: list[Path] = []
    for node in nodes:
        paths.append(
            ingest_brain_node(
                store,
                node,
                automatic=automatic,
                manual_write=manual_write,
                strict_artifact_refs=strict_artifact_refs,
            )
        )
    return paths


def _require_ingest_allowed(
    node: BrainNode, *, automatic: bool, manual_write: bool = False
) -> None:
    if isinstance(node, SkillRunRecord):
        require_explicit_skill_run_writeback(node, automatic=automatic)
        return

    require_write_allowed(node, automatic=automatic, manual_write=manual_write)
