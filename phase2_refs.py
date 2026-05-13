from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlparse

from phase2_brain_models import BrainNode, Route


class Phase2RefKind(StrEnum):
    ARTIFACT = "artifact"
    BRAIN_NODE = "brain_node"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


BRAIN_NODE_REF_PREFIXES: tuple[str, ...] = (
    "beacon.",
    "case.",
    "checkpoint.",
    "device.",
    "equipment.",
    "event.",
    "fact.",
    "interpretation.",
    "measurement.",
    "mission.",
    "option.",
    "option_set.",
    "options.",
    "person.",
    "remote_status.",
    "review.",
    "route.",
    "segment.",
    "signal.",
    "skill.",
    "skill_run.",
    "team.",
)

EXTERNAL_REF_SCHEMES: set[str] = {
    "file",
    "ftp",
    "gs",
    "http",
    "https",
    "s3",
}


def classify_phase2_ref(ref: str) -> Phase2RefKind:
    if not ref:
        return Phase2RefKind.UNKNOWN

    if ref.startswith("artifact."):
        return Phase2RefKind.ARTIFACT

    if ref.startswith(BRAIN_NODE_REF_PREFIXES):
        return Phase2RefKind.BRAIN_NODE

    parsed = urlparse(ref)
    if parsed.scheme in EXTERNAL_REF_SCHEMES and (parsed.netloc or parsed.path):
        return Phase2RefKind.EXTERNAL

    if "/" in ref:
        return Phase2RefKind.EXTERNAL

    return Phase2RefKind.UNKNOWN


def explicit_artifact_ref_candidates_for(node: BrainNode) -> list[str]:
    refs = list(node.artifact_refs)
    if isinstance(node, Route):
        refs.extend(node.source_artifact_refs)
    return refs


def explicit_artifact_refs_for(node: BrainNode) -> list[str]:
    return [
        ref
        for ref in explicit_artifact_ref_candidates_for(node)
        if classify_phase2_ref(ref) == Phase2RefKind.ARTIFACT
    ]
