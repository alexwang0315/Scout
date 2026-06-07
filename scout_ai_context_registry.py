from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from scout_ai_tool_contracts import (
    ScoutAiToolBaseModel,
    ScoutAiToolBoundary,
    default_tool_contracts,
)
from scout_energy_vitals_tool import ENERGY_VITALS_TOOL_ID
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID
from scout_workspace_search_tools import (
    EVIDENCE_FULLTEXT_TOOL_ID,
    MAJOR_POINT_TOOL_ID,
    ROUTE_STRUCTURE_TOOL_ID,
    WORKSPACE_CATALOG_TOOL_ID,
)


ARTIFACT_KIND = "scout_ai_context_registry"
ARTIFACT_VERSION = "scout_ai_context_registry.v0"
WEATHER_WINDOW_TOOL_ID = "scout.ai.weather_window.assess.v0"


class ScoutAiContextSourceStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    MISSING = "missing"


class ScoutAiContextSourceEntry(ScoutAiToolBaseModel):
    source_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: ScoutAiContextSourceStatus
    source_paths: list[str] = Field(default_factory=list)
    missing_paths: list[str] = Field(default_factory=list)
    counts: dict[str, int | float | str | bool] = Field(default_factory=dict)
    tool_ids: list[str] = Field(default_factory=list)
    implementation_status_by_tool: dict[str, str] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    evidence_types: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    candidate_only: Literal[True] = True
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


class ScoutAiContextRegistryOutput(ScoutAiToolBaseModel):
    artifact_kind: Literal["scout_ai_context_registry"] = ARTIFACT_KIND
    artifact_version: Literal["scout_ai_context_registry.v0"] = ARTIFACT_VERSION
    project_id: str
    project_root: str
    source_count: int = Field(ge=0)
    available_source_count: int = Field(default=0, ge=0)
    partial_source_count: int = Field(default=0, ge=0)
    missing_source_count: int = Field(default=0, ge=0)
    source_ids_by_domain: dict[str, list[str]] = Field(default_factory=dict)
    sources: list[ScoutAiContextSourceEntry] = Field(default_factory=list)
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


def discover_scout_ai_context_sources(
    project_root: Path | str,
    *,
    include_missing: bool = True,
) -> ScoutAiContextRegistryOutput:
    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    contracts = default_tool_contracts()

    entries = [
        _entry_from_spec(root, project, contracts, spec)
        for spec in _source_specs()
    ]
    if not include_missing:
        entries = [
            entry
            for entry in entries
            if entry.status != ScoutAiContextSourceStatus.MISSING
        ]

    source_ids_by_domain: dict[str, list[str]] = {}
    for entry in entries:
        source_ids_by_domain.setdefault(entry.domain, []).append(entry.source_id)

    return ScoutAiContextRegistryOutput(
        project_id=project_id,
        project_root=str(root),
        source_count=len(entries),
        available_source_count=sum(
            1 for entry in entries if entry.status == ScoutAiContextSourceStatus.AVAILABLE
        ),
        partial_source_count=sum(
            1 for entry in entries if entry.status == ScoutAiContextSourceStatus.PARTIAL
        ),
        missing_source_count=sum(
            1 for entry in entries if entry.status == ScoutAiContextSourceStatus.MISSING
        ),
        source_ids_by_domain=dict(sorted(source_ids_by_domain.items())),
        sources=entries,
    )


def _entry_from_spec(
    root: Path,
    project: dict[str, Any],
    contracts: dict[str, Any],
    spec: dict[str, Any],
) -> ScoutAiContextSourceEntry:
    source_paths: list[str] = []
    missing_paths: list[str] = []

    for ref_key in spec.get("ref_keys", []):
        ref_value = project.get(ref_key)
        if not isinstance(ref_value, str) or not ref_value.strip():
            missing_paths.append(str(ref_key))
            continue
        if _project_path(root, ref_value).exists():
            source_paths.append(ref_value)
        else:
            missing_paths.append(ref_value)

    for literal_path in spec.get("literal_paths", []):
        value = str(literal_path)
        if _project_path(root, value).exists():
            source_paths.append(value)
        else:
            missing_paths.append(value)

    minimum_existing = int(spec.get("minimum_existing", 1))
    if len(source_paths) >= minimum_existing and not _contract_missing_fields(
        spec,
        contracts,
    ):
        status = ScoutAiContextSourceStatus.AVAILABLE
    elif source_paths:
        status = ScoutAiContextSourceStatus.PARTIAL
    else:
        status = ScoutAiContextSourceStatus.MISSING

    missing_fields = _missing_fields_for_spec(spec, contracts)
    if status == ScoutAiContextSourceStatus.MISSING:
        missing_fields = [*missing_fields, *spec.get("missing_when_absent", [])]

    return ScoutAiContextSourceEntry(
        source_id=str(spec["source_id"]),
        domain=str(spec["domain"]),
        label=str(spec["label"]),
        status=status,
        source_paths=source_paths,
        missing_paths=missing_paths,
        counts=_counts_for_spec(project, root, spec, source_paths),
        tool_ids=list(spec.get("tool_ids", [])),
        implementation_status_by_tool=_implementation_status_by_tool(
            spec.get("tool_ids", []),
            contracts,
        ),
        missing_fields=_dedupe(missing_fields),
        evidence_types=list(spec.get("evidence_types", [])),
        limitations=[
            "Read-only source discovery; candidate/planning evidence only; not runtime safety truth.",
            *spec.get("limitations", []),
        ],
    )


def _source_specs() -> list[dict[str, Any]]:
    return [
        {
            "source_id": "scout.context.workspace_catalog",
            "domain": "workspace",
            "label": "Workspace artifact catalog",
            "ref_keys": [],
            "minimum_existing": 0,
            "tool_ids": [WORKSPACE_CATALOG_TOOL_ID, EVIDENCE_FULLTEXT_TOOL_ID],
            "evidence_types": ["workspace_artifact_ref", "fulltext_evidence"],
        },
        {
            "source_id": "scout.context.route_structure",
            "domain": "route",
            "label": "Route, checkpoint, and segment structure",
            "ref_keys": [
                "route_summary_ref",
                "checkpoint_candidates_ref",
                "segment_candidates_ref",
            ],
            "count_keys": ["checkpoint_candidate_count", "segment_candidate_count"],
            "tool_ids": [ROUTE_STRUCTURE_TOOL_ID],
            "evidence_types": ["route_summary", "checkpoint", "segment"],
        },
        {
            "source_id": "scout.context.major_points",
            "domain": "mcp",
            "label": "MCP, named point, and CP support evidence",
            "ref_keys": [
                "mcp_candidates_ref",
                "mcp_cp_support_reconciliation_ref",
                "mcp_named_point_evidence_ref",
                "mcp_ocr_labels_ref",
            ],
            "count_keys": [
                "mcp_candidate_count",
                "mcp_cp_support_supported_count",
                "mcp_ocr_label_count",
            ],
            "tool_ids": [MAJOR_POINT_TOOL_ID],
            "evidence_types": ["major_point", "named_point", "major_point_cp_support"],
        },
        {
            "source_id": "scout.context.risk_scores",
            "domain": "risk",
            "label": "Baseline and calibrated risk score layers",
            "ref_keys": ["risk_ribbon_ref", "risk_ribbon_metadata_ref"],
            "count_keys": ["risk_ribbon_segment_count"],
            "tool_ids": [RISK_SCORE_TOOL_ID],
            "evidence_types": ["risk_ribbon", "risk_score"],
            "limitations": [
                "Risk scores are planning evidence and cannot trigger Ln or safety admission directly.",
            ],
        },
        {
            "source_id": "scout.context.terrain_scores",
            "domain": "terrain",
            "label": "Terrain, DTM coverage, and slope proxy layers",
            "ref_keys": [
                "segment_dtm_coverage_ref",
                "dtm_coverage_summary_ref",
                "contour_interpretation_candidates_ref",
            ],
            "count_keys": [
                "dtm_candidate_tile_count",
                "contour_interpretation_candidate_count",
            ],
            "tool_ids": [TERRAIN_SCORE_TOOL_ID],
            "evidence_types": ["terrain_score", "dtm_coverage", "contour_candidate"],
        },
        {
            "source_id": "scout.context.map_perception",
            "domain": "map",
            "label": "Map perception, OCR, annotation, and tile evidence",
            "ref_keys": [
                "gis_perception_candidates_ref",
                "gis_perception_ai_judgements_ref",
                "map_context_ref",
                "overpass_map_context_ref",
                "mcp_ocr_labels_ref",
            ],
            "count_keys": [
                "gis_perception_checkpoint_candidate_count",
                "gis_perception_ai_judgement_count",
                "mcp_ocr_label_count",
            ],
            "tool_ids": [MAP_PERCEPTION_TOOL_ID],
            "evidence_types": ["map_perception", "ocr_label", "annotation"],
            "limitations": [
                "Current tool searches existing interpreted map material; it does not run live OCR or VLM inference.",
            ],
        },
        {
            "source_id": "scout.context.weather_window",
            "domain": "weather",
            "label": "Weather/daylight window evidence",
            "ref_keys": ["weather_daylight_evidence_ref"],
            "count_keys": ["weather_daylight_evidence_count"],
            "tool_ids": [WEATHER_WINDOW_TOOL_ID],
            "evidence_types": ["weather_daylight_candidate"],
            "limitations": [
                "Fresh provider, forecast issue time, and TTL evidence are required before weather answers.",
            ],
        },
        {
            "source_id": "scout.context.sensor_vitals",
            "domain": "health",
            "label": "Wearable sensor and vitals records",
            "literal_paths": ["outputs/sensorlogger_mqtt_sensor_vitals_records.jsonl"],
            "tool_ids": [ENERGY_VITALS_TOOL_ID],
            "evidence_types": ["sensor_vitals_record", "energy_vitals_snapshot"],
            "missing_when_absent": ["sensor_vitals_records_jsonl"],
            "limitations": [
                "Wearable/vitals evidence is private advisory evidence and is not a medical diagnosis.",
            ],
        },
        {
            "source_id": "scout.context.ins_dr_trace",
            "domain": "navigation",
            "label": "Offline INS/DR, PDR, and GPS trace evidence",
            "literal_paths": ["outputs/navigation/ins_dr_estimates.jsonl"],
            "tool_ids": [INS_DR_TRACE_TOOL_ID],
            "evidence_types": ["ins_dr_estimate", "gps_fix", "pdr_sample"],
            "missing_when_absent": ["ins_dr_estimates_jsonl"],
            "limitations": [
                "Trace analysis is offline and does not perform live hardware reads or safety mutation.",
            ],
        },
    ]


def _counts_for_spec(
    project: dict[str, Any],
    root: Path,
    spec: dict[str, Any],
    source_paths: list[str],
) -> dict[str, int | float | str | bool]:
    counts: dict[str, int | float | str | bool] = {}
    for key in spec.get("count_keys", []):
        value = project.get(key)
        if isinstance(value, (int, float, str, bool)):
            counts[str(key)] = value
    for source_path in source_paths:
        if source_path.endswith(".jsonl"):
            counts[f"{source_path}:line_count"] = _jsonl_line_count(
                _project_path(root, source_path)
            )
    return counts


def _implementation_status_by_tool(
    tool_ids: list[str],
    contracts: dict[str, Any],
) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for tool_id in tool_ids:
        contract = contracts.get(tool_id)
        if contract is None:
            statuses[tool_id] = "unregistered"
            continue
        statuses[tool_id] = contract.implementation_status.value
    return statuses


def _missing_fields_for_spec(
    spec: dict[str, Any],
    contracts: dict[str, Any],
) -> list[str]:
    fields = list(spec.get("missing_fields", []))
    fields.extend(_contract_missing_fields(spec, contracts))
    return fields


def _contract_missing_fields(
    spec: dict[str, Any],
    contracts: dict[str, Any],
) -> list[str]:
    fields: list[str] = []
    for tool_id in spec.get("tool_ids", []):
        contract = contracts.get(tool_id)
        if contract is None:
            continue
        if contract.aliases and tool_id != ENERGY_VITALS_TOOL_ID:
            continue
        for field in contract.required_fields:
            if field not in {"project_root", "query"}:
                fields.append(str(field))
    return _dedupe(fields)


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _jsonl_line_count(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped
