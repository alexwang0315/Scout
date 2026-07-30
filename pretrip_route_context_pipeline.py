from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Literal, Self
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pretrip_import import PretripImportRequest, run_pretrip_import
from pretrip_p0_p1_source_collection import (
    DEFAULT_WEB_CASE_EVIDENCE_REF,
    Fetcher,
    collect_pretrip_p0_p1_sources,
)
from pretrip_route_context_collection import (
    ROUTE_CONTEXT_BRIEFING_REF,
    ROUTE_CONTEXT_PACK_REF,
    ROUTE_CONTEXT_POINTS_REF,
    ROUTE_CONTEXT_SOURCE_MANIFEST_REF,
    collect_pretrip_route_context,
)


SCHEMA_VERSION = "scout.route_context_pipeline.v1"
SEMANTIC_REVIEW_SCHEMA_VERSION = "scout.route_context_semantic_review.v1"
RUN_MANIFEST_REF = "outputs/route_context_pipeline/run_manifest.json"
REVIEW_PACKET_REF = "outputs/route_context_pipeline/content_review_packet.json"
SEMANTIC_REVIEW_REF = "outputs/route_context_pipeline/semantic_review_result.json"
BRIEFING_REF = ROUTE_CONTEXT_BRIEFING_REF

STAGE_ORDER = (
    "input_contract",
    "evidence_collection",
    "deterministic_compile",
    "content_review",
)
STAGE_LABELS = {
    "input_contract": "輸入契約",
    "evidence_collection": "證據收集",
    "deterministic_compile": "確定性編譯",
    "content_review": "內容審核",
}

DEFAULT_PREPARATION_LAYERS = (
    "imagery",
    "osm",
    "overpass",
    "terrain",
    "risk-score",
    "risk-ribbon",
    "risk-heatmap",
    "risk-delta",
    "cwa-qpf",
    "soil-moisture",
    "antecedent-rain",
    "cwa-weather",
    "weather",
    "reference-tracks",
    "route",
    "segments",
    "checkpoints",
    "mcp",
    "pois",
    "hazards",
    "corridors",
    "retreat",
    "route-notes",
)

BLOCKED_VISIBLE_COPY = (
    "Route Context Intelligence implementation",
    "Scout AI 產生計畫",
    "compiler",
    "workspace cache",
    "route_context_pack.json",
    "route_context_points.json",
    "source_manifest.json",
    "route_context_briefing.html",
    "Scout Route Context Briefing",
    "prompt",
    "提示詞",
    "模型輸出",
    "deterministic",
    "candidate-only",
    "runtime_safety_truth",
    "live_fetch",
    "media provenance",
    "機器可讀",
    "crawl seed",
    "素材板",
    "講者備註",
    "版型",
    "行前素材狀態",
    "行前候選素材",
    "行前照片與地圖狀態",
    "開場主視覺",
    "圖像準備度",
    "行程畫面覆蓋",
    "畫面偏薄",
    "照片與地圖準備度",
    "圖像導覽",
    "圖像缺口",
    "畫面索引",
    "把可用圖片一次攤開",
    "Scout 行前路線簡報",
    "登山活動簡報",
    "簡報導覽",
    "採圖清單",
    "review candidate",
    "review priority",
    "pretrip briefing",
    "contextual permission",
    "review_state=",
    "sensitivity=",
    "advisory=",
)


class PipelineContractError(RuntimeError):
    pass


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RouteInputContract(_FrozenModel):
    golden_gpx: Path
    reference_dir: Path | None = None
    reference_gpx: tuple[Path, ...] = ()
    keywords: tuple[str, ...] = Field(min_length=1)

    @field_validator("keywords")
    @classmethod
    def _normalize_keywords(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in normalized:
                normalized.append(text)
        if not normalized:
            raise ValueError("route.keywords must contain at least one non-empty value")
        return tuple(normalized)


class PublicSourceRecord(_FrozenModel):
    source_id: str
    source_tier: Literal["P0", "P1"]
    source_family: str
    label: str
    url: str

    @field_validator("source_id", "source_family", "label")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("source record text fields must not be empty")
        return text

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        text = value.strip()
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source record url must be an absolute http(s) URL")
        return text


class SourceCollectionContract(_FrozenModel):
    records: tuple[PublicSourceRecord, ...] = ()
    source_list_html: Path | None = None
    image_list_json: Path | None = None
    image_list_html: Path | None = None
    allow_network_fetch: bool = False
    timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    minimum_evidence_items: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def _require_source_input(self) -> Self:
        if not self.records and not any(
            (
                self.source_list_html,
                self.image_list_json,
                self.image_list_html,
            )
        ):
            raise ValueError(
                "sources must provide records, source_list_html, "
                "image_list_json, or image_list_html"
            )
        return self


class PreparationContract(_FrozenModel):
    import_profile: Literal["mac-workstation", "pi-offline", "pi-online-explicit"] = (
        "pi-offline"
    )
    material_root: Path | None = None
    dtm_dirs: tuple[Path, ...] = ()
    checkpoint_spacing_m: float = Field(default=500.0, gt=0.0)
    max_reference_display_points: int = Field(default=2500, ge=1)
    max_reasonable_gpx_speed_kmh: float = Field(default=120.0, gt=0.0)
    max_previous_gpx_speed_ratio: float = Field(default=8.0, gt=0.0)
    run_layer_preparation: bool = False
    layer_profile: Literal["mac-workstation", "pi-offline", "pi-online-explicit"] = (
        "pi-offline"
    )
    network_mode: Literal["no-network", "explicit-fetch"] = "no-network"
    allow_network_fetch: bool = False
    layers: tuple[str, ...] = DEFAULT_PREPARATION_LAYERS
    route_corridor_m: float = Field(default=500.0, gt=0.0)
    reference_track_corridor_m: float = Field(default=300.0, gt=0.0)
    seed_imagery_cache: bool = False
    imagery_provider_allows_offline_prefetch: bool = False
    imagery_seed_max_tiles: int | None = Field(default=None, ge=1)
    osm_pbf_path: Path | None = None
    osm_pbf_source_url: str | None = None

    @model_validator(mode="after")
    def _validate_network_mode(self) -> Self:
        if self.allow_network_fetch and self.network_mode != "explicit-fetch":
            raise ValueError(
                "preparation.allow_network_fetch requires network_mode=explicit-fetch"
            )
        if (
            self.seed_imagery_cache
            and not self.imagery_provider_allows_offline_prefetch
        ):
            raise ValueError(
                "seed_imagery_cache requires "
                "imagery_provider_allows_offline_prefetch=true"
            )
        return self


class CompileContract(_FrozenModel):
    include_route_notes: bool = True
    limit_route_notes: int = Field(default=80, ge=0)
    route_note_point_policy: Literal["seed_only", "promote_representative"] = (
        "seed_only"
    )


class ContentReviewContract(_FrozenModel):
    semantic_review: Literal["required"] = "required"
    reviewer: Literal["chatgpt-pro", "scout-ai-cloud"] = "chatgpt-pro"
    minimum_source_briefs: int = Field(default=2, ge=0)
    minimum_visible_characters: int = Field(default=800, ge=1)
    minimum_h2_count: int = Field(default=3, ge=0)
    required_source_tiers: tuple[Literal["P0", "P1", "P2"], ...] = ("P0", "P1")
    forbidden_route_terms: tuple[str, ...] = ()

    @field_validator("forbidden_route_terms")
    @classmethod
    def _normalize_forbidden_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in normalized:
                normalized.append(text)
        return tuple(normalized)


class RouteContextPipelineContract(_FrozenModel):
    schema_version: Literal[SCHEMA_VERSION]
    project_id: str
    workspace_root: Path
    route: RouteInputContract
    sources: SourceCollectionContract
    preparation: PreparationContract = PreparationContract()
    compile: CompileContract = CompileContract()
    review: ContentReviewContract = ContentReviewContract()

    @field_validator("project_id")
    @classmethod
    def _safe_project_id(cls, value: str) -> str:
        text = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", text):
            raise ValueError(
                "project_id must be a single safe path segment using "
                "letters, numbers, dot, underscore, or dash"
            )
        if text in {".", ".."}:
            raise ValueError("project_id must not be dot or dot-dot")
        return text


class SemanticReviewFinding(_FrozenModel):
    severity: Literal["critical", "major", "minor"]
    criterion: str
    problem: str
    evidence: str
    recommendation: str

    @field_validator("criterion", "problem", "evidence", "recommendation")
    @classmethod
    def _required_finding_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("semantic review finding fields must not be empty")
        return text


class SemanticReviewResult(_FrozenModel):
    schema_version: Literal[SEMANTIC_REVIEW_SCHEMA_VERSION]
    project_id: str
    briefing_sha256: str
    review_packet_sha256: str | None = None
    reviewer: Literal["chatgpt-pro", "scout-ai-cloud"]
    provider: str | None = None
    model: str | None = None
    prompt_sha256: str | None = None
    decision_sha256: str | None = None
    verdict: Literal["PASS", "NEEDS_WORK"]
    summary: str
    findings: tuple[SemanticReviewFinding, ...] = ()
    readability_score: int | None = Field(default=None, ge=1, le=5)
    strengths: tuple[str, ...] = ()
    criterion_assessments: tuple[dict[str, Any], ...] = ()
    priority_revisions: tuple[str, ...] = ()
    usage: dict[str, int] = Field(default_factory=dict)
    response_metadata: dict[str, str] = Field(default_factory=dict)
    reviewed_at: str
    boundary: dict[str, bool] | None = None

    @field_validator(
        "briefing_sha256",
        "review_packet_sha256",
        "prompt_sha256",
        "decision_sha256",
    )
    @classmethod
    def _sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", text):
            raise ValueError("review hashes must be SHA-256 hex digests")
        return text

    @field_validator("summary")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("semantic review summary is required")
        return text

    @field_validator("reviewed_at")
    @classmethod
    def _reviewed_at(cls, value: str) -> str:
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("reviewed_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError("reviewed_at must include a timezone")
        return text

    @model_validator(mode="after")
    def _needs_work_requires_findings(self) -> Self:
        if self.verdict == "NEEDS_WORK" and not self.findings:
            raise ValueError("NEEDS_WORK semantic review must include findings")
        if self.reviewer == "scout-ai-cloud":
            missing = [
                field_name
                for field_name, value in (
                    ("review_packet_sha256", self.review_packet_sha256),
                    ("provider", self.provider),
                    ("model", self.model),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "scout-ai-cloud semantic review is missing "
                    + ", ".join(missing)
                )
        return self


def load_pipeline_contract(
    config_path: Path | str,
) -> RouteContextPipelineContract:
    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise PipelineContractError(f"pipeline config not found: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PipelineContractError(
            f"pipeline config could not be parsed: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PipelineContractError("pipeline config must contain a mapping")
    try:
        contract = RouteContextPipelineContract.model_validate(payload)
    except Exception as exc:
        raise PipelineContractError(f"pipeline config is invalid: {exc}") from exc
    return _resolve_contract_paths(contract, path.parent)


def run_route_context_pipeline(
    contract_or_path: RouteContextPipelineContract | Path | str,
    *,
    confirm_network_fetch: bool = False,
    resume: bool = False,
    rerun_from: Literal[
        "evidence_collection", "deterministic_compile", "content_review"
    ]
    | None = None,
    semantic_review_result: Path | str | None = None,
    source_fetcher: Fetcher | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    contract = (
        contract_or_path
        if isinstance(contract_or_path, RouteContextPipelineContract)
        else load_pipeline_contract(contract_or_path)
    )
    _preflight_contract(contract)
    network_requested = bool(
        contract.sources.allow_network_fetch
        or (
            contract.preparation.run_layer_preparation
            and contract.preparation.allow_network_fetch
        )
    )
    project_root = contract.workspace_root / contract.project_id
    config_sha256 = _contract_sha256(contract)
    if dry_run:
        return _dry_run_plan(
            contract,
            project_root=project_root,
            config_sha256=config_sha256,
            network_confirmed=confirm_network_fetch,
        )
    if network_requested and not confirm_network_fetch:
        raise PipelineContractError(
            "live evidence collection requires --confirm-network-fetch"
        )

    previous = _load_previous_manifest(
        project_root,
        config_sha256=config_sha256,
        resume=resume,
    )
    manifest = previous or _initial_manifest(
        contract,
        project_root=project_root,
        config_sha256=config_sha256,
    )
    if previous is not None:
        input_receipt = _verify_resumed_input_stage(
            contract,
            previous_receipt=(manifest.get("stages") or {}).get("input_contract") or {},
        )
        manifest = _with_stage(manifest, "input_contract", input_receipt)
        manifest = _with_overall_status(manifest)
        _write_run_manifest(project_root, manifest)
        if input_receipt.get("status") != "pass":
            return _public_result(manifest)
    rerun_index = STAGE_ORDER.index(rerun_from) if rerun_from else len(STAGE_ORDER)

    stage_functions: dict[str, Callable[[], dict[str, Any]]] = {
        "input_contract": lambda: _run_input_contract_stage(contract),
        "evidence_collection": lambda: _run_evidence_collection_stage(
            contract,
            source_fetcher=source_fetcher,
        ),
        "deterministic_compile": lambda: _run_compile_stage(contract),
        "content_review": lambda: _run_content_review_stage(
            contract,
            semantic_review_result=semantic_review_result,
        ),
    }

    for index, stage_name in enumerate(STAGE_ORDER):
        prior_stage = (manifest.get("stages") or {}).get(stage_name) or {}
        should_rerun = index >= rerun_index
        if prior_stage.get("status") == "pass" and not should_rerun:
            integrity = _verify_passed_stage_integrity(
                contract,
                stage_name=stage_name,
                receipt=prior_stage,
            )
            if integrity["status"] != "pass":
                receipt = {
                    **prior_stage,
                    "status": "failed",
                    "completed_at": _utc_now(),
                    "resume_integrity": integrity,
                }
                manifest = _with_stage(manifest, stage_name, receipt)
                manifest = _with_overall_status(manifest)
                _write_run_manifest(project_root, manifest)
                break
            continue
        receipt = _execute_stage(stage_name, stage_functions[stage_name])
        manifest = _with_stage(manifest, stage_name, receipt)
        manifest = _with_overall_status(manifest)
        _write_run_manifest(project_root, manifest)
        if receipt.get("status") not in {"pass", "pending"}:
            break
        if receipt.get("status") == "pending":
            break

    manifest = _with_overall_status(manifest)
    _write_run_manifest(project_root, manifest)
    return _public_result(manifest)


def _resolve_contract_paths(
    contract: RouteContextPipelineContract,
    base: Path,
) -> RouteContextPipelineContract:
    route = contract.route.model_copy(
        update={
            "golden_gpx": _resolve_path(contract.route.golden_gpx, base),
            "reference_dir": _resolve_optional_path(contract.route.reference_dir, base),
            "reference_gpx": tuple(
                _resolve_path(path, base) for path in contract.route.reference_gpx
            ),
        }
    )
    sources = contract.sources.model_copy(
        update={
            "source_list_html": _resolve_optional_path(
                contract.sources.source_list_html, base
            ),
            "image_list_json": _resolve_optional_path(
                contract.sources.image_list_json, base
            ),
            "image_list_html": _resolve_optional_path(
                contract.sources.image_list_html, base
            ),
        }
    )
    preparation = contract.preparation.model_copy(
        update={
            "material_root": _resolve_optional_path(
                contract.preparation.material_root, base
            ),
            "dtm_dirs": tuple(
                _resolve_path(path, base) for path in contract.preparation.dtm_dirs
            ),
            "osm_pbf_path": _resolve_optional_path(
                contract.preparation.osm_pbf_path, base
            ),
        }
    )
    return contract.model_copy(
        update={
            "workspace_root": _resolve_path(contract.workspace_root, base),
            "route": route,
            "sources": sources,
            "preparation": preparation,
        }
    )


def _resolve_path(path: Path, base: Path) -> Path:
    expanded = path.expanduser()
    return (expanded if expanded.is_absolute() else base / expanded).resolve()


def _resolve_optional_path(path: Path | None, base: Path) -> Path | None:
    return _resolve_path(path, base) if path is not None else None


def _preflight_contract(contract: RouteContextPipelineContract) -> None:
    errors: list[str] = []
    if not contract.route.golden_gpx.is_file():
        errors.append(f"golden GPX not found: {contract.route.golden_gpx}")
    if (
        contract.route.reference_dir is not None
        and not contract.route.reference_dir.is_dir()
    ):
        errors.append(
            f"reference GPX directory not found: {contract.route.reference_dir}"
        )
    for path in contract.route.reference_gpx:
        if not path.is_file():
            errors.append(f"reference GPX not found: {path}")
    for label, path in (
        ("source list HTML", contract.sources.source_list_html),
        ("image list JSON", contract.sources.image_list_json),
        ("image list HTML", contract.sources.image_list_html),
        ("material root", contract.preparation.material_root),
        ("local OSM PBF", contract.preparation.osm_pbf_path),
    ):
        if path is not None and not path.exists():
            errors.append(f"{label} not found: {path}")
    for path in contract.preparation.dtm_dirs:
        if not path.is_dir():
            errors.append(f"DTM directory not found: {path}")
    if contract.workspace_root.exists() and not contract.workspace_root.is_dir():
        errors.append(f"workspace_root is not a directory: {contract.workspace_root}")
    if errors:
        raise PipelineContractError("; ".join(errors))


def _load_previous_manifest(
    project_root: Path,
    *,
    config_sha256: str,
    resume: bool,
) -> dict[str, Any] | None:
    if not project_root.exists():
        if resume:
            raise PipelineContractError(
                f"--resume requested but project workspace does not exist: {project_root}"
            )
        return None
    if not resume:
        raise PipelineContractError(
            f"project workspace already exists; use --resume only for the same "
            f"pipeline run: {project_root}"
        )
    manifest_path = project_root / RUN_MANIFEST_REF
    if not manifest_path.is_file():
        raise PipelineContractError(
            "existing project is not owned by this one-click pipeline; "
            "--resume is refused"
        )
    manifest = _load_json_object(manifest_path)
    if manifest.get("config_sha256") != config_sha256:
        raise PipelineContractError(
            "pipeline config changed since the existing run; create a new project_id "
            "or restore the original contract"
        )
    return manifest


def _initial_manifest(
    contract: RouteContextPipelineContract,
    *,
    project_root: Path,
    config_sha256: str,
) -> dict[str, Any]:
    now = _utc_now()
    return {
        "artifact_kind": "pretrip_route_context_pipeline_run",
        "schema_version": SCHEMA_VERSION,
        "run_id": f"route-context-{uuid.uuid4().hex[:12]}",
        "project_id": contract.project_id,
        "project_root": str(project_root),
        "config_sha256": config_sha256,
        "status": "running",
        "started_at": now,
        "updated_at": now,
        "stages": {
            stage: {
                "stage": stage,
                "stage_label": STAGE_LABELS[stage],
                "status": "not_started",
            }
            for stage in STAGE_ORDER
        },
        "outputs": {
            "run_manifest_ref": RUN_MANIFEST_REF,
            "review_packet_ref": REVIEW_PACKET_REF,
            "semantic_review_ref": SEMANTIC_REVIEW_REF,
            "briefing_ref": BRIEFING_REF,
        },
        "boundary": _boundary(),
    }


def _run_input_contract_stage(
    contract: RouteContextPipelineContract,
) -> dict[str, Any]:
    project_root = contract.workspace_root / contract.project_id
    if project_root.exists():
        raise PipelineContractError(
            f"new pipeline input must not overwrite an existing workspace: {project_root}"
        )
    contract.workspace_root.mkdir(parents=True, exist_ok=True)
    fingerprints = _input_fingerprints(contract)
    request = PretripImportRequest(
        project_id=contract.project_id,
        primary_gpx=contract.route.golden_gpx,
        workspace_root=contract.workspace_root,
        reference_dir=contract.route.reference_dir,
        reference_gpx_paths=contract.route.reference_gpx,
        profile=contract.preparation.import_profile,
        checkpoint_spacing_m=contract.preparation.checkpoint_spacing_m,
        max_reference_display_points=(
            contract.preparation.max_reference_display_points
        ),
        max_reasonable_gpx_speed_kmh=(
            contract.preparation.max_reasonable_gpx_speed_kmh
        ),
        max_previous_gpx_speed_ratio=(
            contract.preparation.max_previous_gpx_speed_ratio
        ),
        material_root=contract.preparation.material_root,
        dtm_dirs=contract.preparation.dtm_dirs,
        overwrite=False,
        import_stage="pretrip",
    )
    result = run_pretrip_import(request)
    project = _load_json_object(project_root / "project.json")
    if _project_id(project, project_root) != contract.project_id:
        raise PipelineContractError("imported workspace project_id binding mismatch")
    return {
        "status": "pass",
        "completed_at": _utc_now(),
        "checks": [
            {
                "check_id": "project_binding",
                "status": "pass",
                "project_id": contract.project_id,
            },
            {
                "check_id": "input_files",
                "status": "pass",
                "fingerprints": fingerprints,
            },
            {
                "check_id": "non_destructive_create",
                "status": "pass",
                "overwrite": False,
            },
        ],
        "input_fingerprints": fingerprints,
        "import": {
            "status": "completed",
            "profile": result.get("profile"),
            "counts": result.get("counts") or {},
            "import_manifest_ref": project.get("import_manifest_ref"),
            "route_summary_ref": project.get("route_summary_ref"),
            "route_evidence_bundle_ref": project.get("route_evidence_bundle_ref"),
        },
        "boundary": _boundary(),
    }


def _verify_resumed_input_stage(
    contract: RouteContextPipelineContract,
    *,
    previous_receipt: dict[str, Any],
) -> dict[str, Any]:
    project_root = contract.workspace_root / contract.project_id
    project = _load_json_object(project_root / "project.json")
    actual_project_id = _project_id(project, project_root)
    current_fingerprints = _input_fingerprints(contract)
    expected_fingerprints = previous_receipt.get("input_fingerprints")
    project_matches = actual_project_id == contract.project_id
    inputs_match = current_fingerprints == expected_fingerprints
    status = "pass" if project_matches and inputs_match else "failed"
    return {
        "status": status,
        "completed_at": _utc_now(),
        "resumed": True,
        "checks": [
            {
                "check_id": "project_binding",
                "status": "pass" if project_matches else "failed",
                "expected_project_id": contract.project_id,
                "actual_project_id": actual_project_id,
            },
            {
                "check_id": "input_files",
                "status": "pass" if inputs_match else "failed",
                "expected_fingerprints": expected_fingerprints,
                "actual_fingerprints": current_fingerprints,
            },
        ],
        "input_fingerprints": current_fingerprints,
        "boundary": _boundary(),
    }


def _verify_passed_stage_integrity(
    contract: RouteContextPipelineContract,
    *,
    stage_name: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    project_root = contract.workspace_root / contract.project_id
    checks: list[dict[str, Any]] = []

    if stage_name == "input_contract":
        checks.append(
            _check(
                "resumed_input_contract",
                receipt.get("status") == "pass",
            )
        )
    elif stage_name == "evidence_collection":
        public_sources = receipt.get("public_source_collection") or {}
        checks.append(
            _artifact_hash_check(
                project_root,
                DEFAULT_WEB_CASE_EVIDENCE_REF,
                public_sources.get("web_case_evidence_sha256"),
            )
        )
    elif stage_name == "deterministic_compile":
        outputs = receipt.get("outputs") or {}
        for ref in (
            ROUTE_CONTEXT_SOURCE_MANIFEST_REF,
            ROUTE_CONTEXT_PACK_REF,
            ROUTE_CONTEXT_POINTS_REF,
            BRIEFING_REF,
        ):
            metadata = outputs.get(ref) or {}
            checks.append(
                _artifact_hash_check(
                    project_root,
                    ref,
                    metadata.get("sha256"),
                )
            )
    elif stage_name == "content_review":
        checks.extend(
            (
                _artifact_hash_check(
                    project_root,
                    BRIEFING_REF,
                    receipt.get("briefing_sha256"),
                ),
                _artifact_hash_check(
                    project_root,
                    REVIEW_PACKET_REF,
                    receipt.get("review_packet_sha256"),
                ),
                _artifact_hash_check(
                    project_root,
                    SEMANTIC_REVIEW_REF,
                    receipt.get("semantic_review_sha256"),
                ),
            )
        )
        semantic_path = project_root / SEMANTIC_REVIEW_REF
        semantic_valid = False
        semantic_details: dict[str, Any] = {}
        if semantic_path.is_file():
            try:
                review = SemanticReviewResult.model_validate(
                    _load_json_object(semantic_path)
                )
                semantic_valid = bool(
                    review.project_id == contract.project_id
                    and review.briefing_sha256 == receipt.get("briefing_sha256")
                    and review.verdict == "PASS"
                )
                semantic_details = {
                    "actual_project_id": review.project_id,
                    "actual_briefing_sha256": review.briefing_sha256,
                    "actual_verdict": review.verdict,
                }
            except Exception as exc:
                semantic_details = {"error": str(exc)}
        checks.append(
            _check(
                "semantic_review_binding",
                semantic_valid,
                expected_project_id=contract.project_id,
                expected_briefing_sha256=receipt.get("briefing_sha256"),
                expected_verdict="PASS",
                **semantic_details,
            )
        )
    else:
        checks.append(
            _check(
                "known_stage",
                False,
                stage_name=stage_name,
            )
        )

    failed = [check["check_id"] for check in checks if check["status"] == "failed"]
    return {
        "status": "pass" if not failed else "failed",
        "checked_at": _utc_now(),
        "checks": checks,
        "failed_check_ids": failed,
    }


def _artifact_hash_check(
    project_root: Path,
    ref: str,
    expected_sha256: Any,
) -> dict[str, Any]:
    path = project_root / ref
    exists = path.is_file()
    actual_sha256 = _sha256_file(path) if exists else None
    expected = (
        str(expected_sha256).strip().lower() if expected_sha256 is not None else None
    )
    valid_expected = bool(expected and re.fullmatch(r"[0-9a-f]{64}", expected))
    return _check(
        f"artifact_hash:{ref}",
        bool(exists and valid_expected and actual_sha256 == expected),
        ref=ref,
        exists=exists,
        expected_sha256=expected,
        actual_sha256=actual_sha256,
    )


def _run_evidence_collection_stage(
    contract: RouteContextPipelineContract,
    *,
    source_fetcher: Fetcher | None,
) -> dict[str, Any]:
    project_root = contract.workspace_root / contract.project_id
    layer_summary: dict[str, Any] = {
        "status": "not_requested",
        "network_calls_made": False,
    }
    if contract.preparation.run_layer_preparation:
        from pretrip_layer_preparation import (
            LayerPreparationRequest,
            run_layer_preparation,
        )

        layer_result = run_layer_preparation(
            LayerPreparationRequest(
                project_id=contract.project_id,
                workspace_root=contract.workspace_root,
                layers=contract.preparation.layers,
                profile=contract.preparation.layer_profile,
                network_mode=contract.preparation.network_mode,
                allow_network_fetch=contract.preparation.allow_network_fetch,
                route_corridor_m=contract.preparation.route_corridor_m,
                reference_track_corridor_m=(
                    contract.preparation.reference_track_corridor_m
                ),
                seed_imagery_cache=contract.preparation.seed_imagery_cache,
                imagery_provider_allows_offline_prefetch=(
                    contract.preparation.imagery_provider_allows_offline_prefetch
                ),
                imagery_seed_max_tiles=(contract.preparation.imagery_seed_max_tiles),
                osm_pbf_path=contract.preparation.osm_pbf_path,
                osm_pbf_source_url=contract.preparation.osm_pbf_source_url,
            )
        )
        validation = layer_result.get("validation") or {}
        blockers = validation.get("blockers") or []
        if blockers:
            raise RuntimeError(f"layer preparation produced {len(blockers)} blocker(s)")
        layer_summary = {
            "status": "completed",
            "requested_layers": list(contract.preparation.layers),
            "network_calls_made": bool(
                (layer_result.get("network_policy") or {}).get("network_calls_made")
            ),
            "validation_status": validation.get("status"),
            "blocker_count": len(blockers),
            "warning_count": len(validation.get("warnings") or []),
        }

    source_result = collect_pretrip_p0_p1_sources(
        project_root,
        allow_network_fetch=contract.sources.allow_network_fetch,
        dry_run=False,
        source_records=[
            record.model_dump(mode="json") for record in contract.sources.records
        ],
        source_list_html=contract.sources.source_list_html,
        image_list_json=contract.sources.image_list_json,
        image_list_html=contract.sources.image_list_html,
        route_keywords=list(contract.route.keywords),
        timeout_seconds=contract.sources.timeout_seconds,
        fetcher=source_fetcher,
    )
    evidence = _load_json_object(project_root / DEFAULT_WEB_CASE_EVIDENCE_REF)
    evidence_count = int(source_result.get("evidence_item_count") or 0)
    if evidence_count < contract.sources.minimum_evidence_items:
        raise RuntimeError(
            "evidence collection did not meet minimum_evidence_items: "
            f"{evidence_count} < {contract.sources.minimum_evidence_items}"
        )
    return {
        "status": "pass",
        "completed_at": _utc_now(),
        "layer_preparation": layer_summary,
        "public_source_collection": {
            "status": evidence.get("status"),
            "source_count": source_result.get("source_count"),
            "image_source_count": source_result.get("image_source_count"),
            "evidence_item_count": evidence_count,
            "network_calls_made": source_result.get("network_calls_made"),
            "counts": evidence.get("counts") or {},
            "web_case_evidence_ref": DEFAULT_WEB_CASE_EVIDENCE_REF,
            "web_case_evidence_sha256": _sha256_file(
                project_root / DEFAULT_WEB_CASE_EVIDENCE_REF
            ),
        },
        "boundary": _boundary(),
    }


def _run_compile_stage(
    contract: RouteContextPipelineContract,
) -> dict[str, Any]:
    project_root = contract.workspace_root / contract.project_id
    result = collect_pretrip_route_context(
        project_root,
        dry_run=False,
        include_route_notes=contract.compile.include_route_notes,
        limit_route_notes=contract.compile.limit_route_notes,
        route_note_point_policy=contract.compile.route_note_point_policy,
        route_keyword=contract.route.keywords[0],
        write_briefing=True,
    )
    refs = (
        ROUTE_CONTEXT_SOURCE_MANIFEST_REF,
        ROUTE_CONTEXT_PACK_REF,
        ROUTE_CONTEXT_POINTS_REF,
        BRIEFING_REF,
    )
    missing = [ref for ref in refs if not (project_root / ref).is_file()]
    if missing:
        raise RuntimeError(f"deterministic compile missing outputs: {missing}")
    binding_mismatches = _artifact_binding_mismatches(
        project_root,
        contract.project_id,
        refs[:-1],
    )
    if binding_mismatches:
        raise RuntimeError(
            f"deterministic compile project binding mismatch: {binding_mismatches}"
        )
    return {
        "status": "pass",
        "completed_at": _utc_now(),
        "point_count": result.get("point_count"),
        "route_mileage_k_anchor_count": result.get("route_mileage_k_anchor_count"),
        "source_report": result.get("source_report") or [],
        "outputs": {
            ref: {
                "exists": True,
                "sha256": _sha256_file(project_root / ref),
            }
            for ref in refs
        },
        "boundary": _boundary(),
    }


def _run_content_review_stage(
    contract: RouteContextPipelineContract,
    *,
    semantic_review_result: Path | str | None,
) -> dict[str, Any]:
    project_root = contract.workspace_root / contract.project_id
    deterministic = _deterministic_content_review(contract)
    briefing_path = project_root / BRIEFING_REF
    briefing_sha256 = _sha256_file(briefing_path)
    packet = _build_review_packet(
        contract,
        deterministic_review=deterministic,
        briefing_sha256=briefing_sha256,
    )
    _write_json(project_root / REVIEW_PACKET_REF, packet)
    review_packet_sha256 = _sha256_file(project_root / REVIEW_PACKET_REF)
    if deterministic["status"] != "pass":
        return {
            "status": "failed",
            "completed_at": _utc_now(),
            "deterministic_review": deterministic,
            "semantic_review": {
                "status": "blocked",
                "reason": "deterministic_review_failed",
            },
            "briefing_sha256": briefing_sha256,
            "review_packet_ref": REVIEW_PACKET_REF,
            "review_packet_sha256": review_packet_sha256,
            "boundary": _boundary(),
        }

    semantic = _semantic_review(
        contract,
        briefing_sha256=briefing_sha256,
        review_packet_sha256=review_packet_sha256,
        review_result_path=semantic_review_result,
    )
    if semantic["status"] == "pass":
        stage_status = "pass"
    elif semantic["status"] == "pending":
        stage_status = "pending"
    else:
        stage_status = "failed"
    return {
        "status": stage_status,
        "completed_at": _utc_now(),
        "deterministic_review": deterministic,
        "semantic_review": semantic,
        "briefing_sha256": briefing_sha256,
        "review_packet_ref": REVIEW_PACKET_REF,
        "review_packet_sha256": review_packet_sha256,
        "semantic_review_sha256": (
            _sha256_file(project_root / SEMANTIC_REVIEW_REF)
            if (project_root / SEMANTIC_REVIEW_REF).is_file()
            else None
        ),
        "boundary": _boundary(),
    }


def _deterministic_content_review(
    contract: RouteContextPipelineContract,
) -> dict[str, Any]:
    project_root = contract.workspace_root / contract.project_id
    briefing_path = project_root / BRIEFING_REF
    html = briefing_path.read_text(encoding="utf-8")
    parser = _VisibleTextParser()
    parser.feed(html)
    visible_text = re.sub(r"\s+", " ", " ".join(parser.text)).strip()

    project = _load_json_object(project_root / "project.json")
    source_manifest = _load_json_object(
        project_root / ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    )
    pack = _load_json_object(project_root / ROUTE_CONTEXT_PACK_REF)
    points = _load_json_object(project_root / ROUTE_CONTEXT_POINTS_REF)
    web_evidence = _load_json_object(project_root / DEFAULT_WEB_CASE_EVIDENCE_REF)

    binding_mismatches = _artifact_binding_mismatches(
        project_root,
        contract.project_id,
        (
            "project.json",
            ROUTE_CONTEXT_SOURCE_MANIFEST_REF,
            ROUTE_CONTEXT_PACK_REF,
            ROUTE_CONTEXT_POINTS_REF,
            DEFAULT_WEB_CASE_EVIDENCE_REF,
        ),
    )
    route_keyword_hits = [
        keyword for keyword in contract.route.keywords if keyword in visible_text
    ]
    allowed_route_text = " ".join(contract.route.keywords)
    forbidden_terms = [
        term
        for term in contract.review.forbidden_route_terms
        if term not in allowed_route_text
    ]
    found_forbidden_terms = [term for term in forbidden_terms if term in visible_text]
    blocked_copy = [
        term
        for term in BLOCKED_VISIBLE_COPY
        if term.casefold() in visible_text.casefold()
    ]
    briefs = source_manifest.get("route_source_briefs") or []
    brief_tiers = {
        str(item.get("source_tier"))
        for item in briefs
        if isinstance(item, dict) and item.get("source_tier")
    }
    missing_tiers = [
        tier
        for tier in contract.review.required_source_tiers
        if tier not in brief_tiers
    ]
    evidence_items = web_evidence.get("evidence_items") or []
    pack_boundary = pack.get("boundary") or {}
    points_boundary = points.get("boundary") or {}
    boundary_ok = bool(
        pack_boundary.get("candidate_only") is True
        and pack_boundary.get("runtime_safety_truth") is False
        and pack_boundary.get("phase1_runtime_mutation_allowed") is False
        and points_boundary.get("candidate_only") is True
        and points_boundary.get("runtime_safety_truth") is False
        and points_boundary.get("phase1_runtime_mutation_allowed") is False
    )
    checks = [
        _check(
            "project_binding",
            not binding_mismatches,
            mismatches=binding_mismatches,
            expected_project_id=contract.project_id,
            actual_project_id=_project_id(project, project_root),
        ),
        _check(
            "route_identity_visible",
            bool(route_keyword_hits),
            route_keyword_hits=route_keyword_hits,
            expected_keywords=list(contract.route.keywords),
        ),
        _check(
            "previous_route_contamination",
            not found_forbidden_terms,
            found_terms=found_forbidden_terms,
            checked_terms=forbidden_terms,
        ),
        _check(
            "product_copy_gate",
            not blocked_copy,
            blocked_visible_terms=blocked_copy,
        ),
        _check(
            "source_brief_coverage",
            len(briefs) >= contract.review.minimum_source_briefs,
            source_brief_count=len(briefs),
            required_count=contract.review.minimum_source_briefs,
        ),
        _check(
            "source_tier_coverage",
            not missing_tiers,
            present_tiers=sorted(brief_tiers),
            missing_tiers=missing_tiers,
        ),
        _check(
            "evidence_materialized",
            len(evidence_items) >= contract.sources.minimum_evidence_items,
            evidence_item_count=len(evidence_items),
            required_count=contract.sources.minimum_evidence_items,
        ),
        _check(
            "readable_document_shape",
            (
                len(visible_text) >= contract.review.minimum_visible_characters
                and parser.heading_counts["h1"] >= 1
                and parser.heading_counts["h2"] >= contract.review.minimum_h2_count
            ),
            visible_character_count=len(visible_text),
            minimum_visible_characters=contract.review.minimum_visible_characters,
            h1_count=parser.heading_counts["h1"],
            h2_count=parser.heading_counts["h2"],
            minimum_h2_count=contract.review.minimum_h2_count,
        ),
        _check(
            "candidate_boundary",
            boundary_ok,
            pack_boundary=pack_boundary,
            points_boundary=points_boundary,
        ),
    ]
    failed = [check["check_id"] for check in checks if check["status"] == "failed"]
    return {
        "status": "pass" if not failed else "failed",
        "checked_at": _utc_now(),
        "briefing_ref": BRIEFING_REF,
        "briefing_sha256": _sha256_file(briefing_path),
        "checks": checks,
        "failed_check_ids": failed,
        "visible_character_count": len(visible_text),
        "boundary": _boundary(),
    }


def _build_review_packet(
    contract: RouteContextPipelineContract,
    *,
    deterministic_review: dict[str, Any],
    briefing_sha256: str,
) -> dict[str, Any]:
    project_root = contract.workspace_root / contract.project_id
    refs = (
        BRIEFING_REF,
        ROUTE_CONTEXT_SOURCE_MANIFEST_REF,
        ROUTE_CONTEXT_PACK_REF,
        ROUTE_CONTEXT_POINTS_REF,
        DEFAULT_WEB_CASE_EVIDENCE_REF,
    )
    return {
        "artifact_kind": "route_context_content_review_packet",
        "schema_version": SCHEMA_VERSION,
        "project_id": contract.project_id,
        "route_keywords": list(contract.route.keywords),
        "objective": (
            f"判斷這份內容是否是一份可直接閱讀的「{contract.route.keywords[0]}」"
            "行前路線導覽，而不是工程報告或來源清單傾倒。"
        ),
        "required_reviewer": contract.review.reviewer,
        "required_verdicts": ["PASS", "NEEDS_WORK"],
        "review_criteria": [
            "路線身分清楚且沒有混入其他旅程內容",
            "行程、交通、申請、裝備、地形、季節及應變資訊有來源或明確缺口",
            "P0/P1/P2 證據層次清楚，不把候選內容寫成現況真值",
            "沒有虛構里程、狀態、天氣、住宿、價格或聯絡方式",
            "章節可供領隊與隊員順序閱讀，重要缺口能轉成下一步查核",
        ],
        "artifacts": [
            {
                "ref": ref,
                "sha256": _sha256_file(project_root / ref),
            }
            for ref in refs
        ],
        "briefing_sha256": briefing_sha256,
        "deterministic_review": {
            key: value
            for key, value in deterministic_review.items()
            if key != "checked_at"
        },
        "expected_result_schema": {
            "schema_version": SEMANTIC_REVIEW_SCHEMA_VERSION,
            "project_id": contract.project_id,
            "briefing_sha256": briefing_sha256,
            "review_packet_sha256": (
                "SHA-256 of this review packet"
                if contract.review.reviewer == "scout-ai-cloud"
                else "optional"
            ),
            "reviewer": contract.review.reviewer,
            "provider": (
                "cloud provider id"
                if contract.review.reviewer == "scout-ai-cloud"
                else "optional"
            ),
            "model": (
                "exact cloud model id"
                if contract.review.reviewer == "scout-ai-cloud"
                else "optional"
            ),
            "verdict": "PASS or NEEDS_WORK",
            "summary": "concise reviewer conclusion",
            "findings": [
                {
                    "severity": "critical, major, or minor",
                    "criterion": "review criterion",
                    "problem": "specific content problem",
                    "evidence": "specific briefing section or wording",
                    "recommendation": "actionable correction",
                }
            ],
            "reviewed_at": "ISO-8601 timestamp",
        },
        "boundary": _boundary(),
    }


def _semantic_review(
    contract: RouteContextPipelineContract,
    *,
    briefing_sha256: str,
    review_packet_sha256: str,
    review_result_path: Path | str | None,
) -> dict[str, Any]:
    mode = contract.review.semantic_review
    if review_result_path is None:
        if mode == "required":
            return {
                "status": "pending",
                "required_reviewer": contract.review.reviewer,
                "review_packet_ref": REVIEW_PACKET_REF,
                "expected_briefing_sha256": briefing_sha256,
                "expected_review_packet_sha256": review_packet_sha256,
            }
        return {
            "status": "not_applicable" if mode == "disabled" else "not_provided",
            "mode": mode,
        }

    path = Path(review_result_path).expanduser().resolve()
    if not path.is_file():
        return {
            "status": "failed",
            "issue_code": "semantic_review_result_missing",
            "path": str(path),
        }
    try:
        review = SemanticReviewResult.model_validate(_load_json_object(path))
    except Exception as exc:
        return {
            "status": "failed",
            "issue_code": "semantic_review_result_invalid",
            "error": str(exc),
        }
    if review.project_id != contract.project_id:
        return {
            "status": "failed",
            "issue_code": "semantic_review_project_mismatch",
            "expected_project_id": contract.project_id,
            "actual_project_id": review.project_id,
        }
    if review.reviewer != contract.review.reviewer:
        return {
            "status": "failed",
            "issue_code": "semantic_review_reviewer_mismatch",
            "expected_reviewer": contract.review.reviewer,
            "actual_reviewer": review.reviewer,
        }
    if review.briefing_sha256 != briefing_sha256:
        return {
            "status": "failed",
            "issue_code": "semantic_review_briefing_hash_mismatch",
            "expected_briefing_sha256": briefing_sha256,
            "actual_briefing_sha256": review.briefing_sha256,
        }
    if (
        review.reviewer == "scout-ai-cloud"
        and review.review_packet_sha256 != review_packet_sha256
    ):
        return {
            "status": "failed",
            "issue_code": "semantic_review_packet_hash_mismatch",
            "expected_review_packet_sha256": review_packet_sha256,
            "actual_review_packet_sha256": review.review_packet_sha256,
        }
    project_root = contract.workspace_root / contract.project_id
    _write_json(
        project_root / SEMANTIC_REVIEW_REF,
        review.model_dump(mode="json"),
    )
    if review.verdict != "PASS":
        return {
            "status": "failed",
            "issue_code": "semantic_review_needs_work",
            **review.model_dump(mode="json"),
            "semantic_review_ref": SEMANTIC_REVIEW_REF,
        }
    return {
        "status": "pass",
        **review.model_dump(mode="json"),
        "semantic_review_ref": SEMANTIC_REVIEW_REF,
    }


def _execute_stage(
    stage_name: str,
    function: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    started_at = _utc_now()
    try:
        result = function()
        return {**result, "started_at": started_at}
    except Exception as exc:
        return {
            "status": "failed",
            "started_at": started_at,
            "completed_at": _utc_now(),
            "stage": stage_name,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "boundary": _boundary(),
        }


def _with_stage(
    manifest: dict[str, Any],
    stage_name: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    labeled_receipt = {
        **receipt,
        "stage": stage_name,
        "stage_label": STAGE_LABELS[stage_name],
    }
    stages = {
        **(manifest.get("stages") or {}),
        stage_name: labeled_receipt,
    }
    return {
        **manifest,
        "stages": stages,
        "updated_at": _utc_now(),
    }


def _with_overall_status(manifest: dict[str, Any]) -> dict[str, Any]:
    stages = manifest.get("stages") or {}
    statuses = {name: (stages.get(name) or {}).get("status") for name in STAGE_ORDER}
    if any(statuses[name] == "failed" for name in STAGE_ORDER[:-1]):
        status = "failed"
    elif statuses["content_review"] == "pass":
        status = "completed"
    elif statuses["content_review"] == "pending":
        status = "needs_semantic_review"
    elif statuses["content_review"] == "failed":
        status = "needs_work"
    else:
        status = "running"
    return {**manifest, "status": status, "updated_at": _utc_now()}


def _write_run_manifest(project_root: Path, manifest: dict[str, Any]) -> None:
    if project_root.exists():
        _write_json(project_root / RUN_MANIFEST_REF, manifest)


def _public_result(manifest: dict[str, Any]) -> dict[str, Any]:
    content_review = (manifest.get("stages") or {}).get("content_review") or {}
    return {
        "artifact_kind": manifest.get("artifact_kind"),
        "schema_version": manifest.get("schema_version"),
        "run_id": manifest.get("run_id"),
        "project_id": manifest.get("project_id"),
        "project_root": manifest.get("project_root"),
        "status": manifest.get("status"),
        "stages": manifest.get("stages") or {},
        "flow": [
            {
                "stage": stage,
                "label": STAGE_LABELS[stage],
                "status": ((manifest.get("stages") or {}).get(stage) or {}).get(
                    "status"
                ),
            }
            for stage in STAGE_ORDER
        ],
        "briefing_ref": BRIEFING_REF,
        "briefing_sha256": content_review.get("briefing_sha256"),
        "review_packet_ref": REVIEW_PACKET_REF,
        "semantic_review_ref": SEMANTIC_REVIEW_REF,
        "run_manifest_ref": RUN_MANIFEST_REF,
        "boundary": manifest.get("boundary") or _boundary(),
    }


def _dry_run_plan(
    contract: RouteContextPipelineContract,
    *,
    project_root: Path,
    config_sha256: str,
    network_confirmed: bool,
) -> dict[str, Any]:
    return {
        "artifact_kind": "pretrip_route_context_pipeline_plan",
        "schema_version": SCHEMA_VERSION,
        "project_id": contract.project_id,
        "project_root": str(project_root),
        "config_sha256": config_sha256,
        "status": "planned",
        "stages": [
            {
                "stage": "input_contract",
                "label": STAGE_LABELS["input_contract"],
                "actions": ["validate inputs", "fingerprint inputs", "import GPX"],
            },
            {
                "stage": "evidence_collection",
                "label": STAGE_LABELS["evidence_collection"],
                "actions": [
                    "optional layer preparation",
                    "collect explicit P0/P1 sources",
                ],
            },
            {
                "stage": "deterministic_compile",
                "label": STAGE_LABELS["deterministic_compile"],
                "actions": ["compile route context artifacts and briefing HTML"],
            },
            {
                "stage": "content_review",
                "label": STAGE_LABELS["content_review"],
                "actions": [
                    "run deterministic content gates",
                    f"semantic review mode: {contract.review.semantic_review}",
                ],
            },
        ],
        "network_requested": bool(
            contract.sources.allow_network_fetch
            or contract.preparation.allow_network_fetch
        ),
        "network_confirmed": network_confirmed,
        "writes_performed": False,
        "boundary": _boundary(),
    }


def _input_fingerprints(
    contract: RouteContextPipelineContract,
) -> dict[str, Any]:
    reference_paths = list(contract.route.reference_gpx)
    if contract.route.reference_dir:
        reference_paths.extend(sorted(contract.route.reference_dir.glob("*.gpx")))
    file_paths = [
        contract.route.golden_gpx,
        *reference_paths,
        *[
            path
            for path in (
                contract.sources.source_list_html,
                contract.sources.image_list_json,
                contract.sources.image_list_html,
            )
            if path is not None
        ],
    ]
    unique_paths: list[Path] = []
    for path in file_paths:
        resolved = path.resolve()
        if resolved not in unique_paths:
            unique_paths.append(resolved)
    return {
        "golden_gpx": {
            "path": str(contract.route.golden_gpx),
            "sha256": _sha256_file(contract.route.golden_gpx),
        },
        "reference_gpx": [
            {"path": str(path), "sha256": _sha256_file(path)}
            for path in unique_paths
            if path.suffix.lower() == ".gpx"
            and path.resolve() != contract.route.golden_gpx.resolve()
        ],
        "source_files": [
            {"path": str(path), "sha256": _sha256_file(path)}
            for path in unique_paths
            if path.suffix.lower() != ".gpx"
        ],
    }


def _artifact_binding_mismatches(
    project_root: Path,
    project_id: str,
    refs: tuple[str, ...],
) -> list[dict[str, str]]:
    mismatches: list[dict[str, str]] = []
    for ref in refs:
        payload = _load_json_object(project_root / ref)
        actual = _project_id(payload, project_root)
        if actual != project_id:
            mismatches.append(
                {
                    "ref": ref,
                    "expected_project_id": project_id,
                    "actual_project_id": actual,
                }
            )
    return mismatches


def _project_id(payload: dict[str, Any], project_root: Path) -> str:
    return str(payload.get("project_id") or payload.get("id") or project_root.name)


def _check(check_id: str, passed: bool, **details: Any) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "pass" if passed else "failed",
        **details,
    }


def _contract_sha256(contract: RouteContextPipelineContract) -> str:
    encoded = json.dumps(
        contract.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PipelineContractError(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PipelineContractError(f"JSON artifact must contain an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _boundary() -> dict[str, bool]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "live_safety_api_calls_allowed": False,
    }


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.heading_counts = {"h1": 0, "h2": 0}
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "svg", "template", "noscript"}:
            self._ignored_depth += 1
        if not self._ignored_depth and lowered in self.heading_counts:
            self.heading_counts[lowered] += 1

    def handle_endtag(self, tag: str) -> None:
        if (
            tag.lower() in {"script", "style", "svg", "template", "noscript"}
            and self._ignored_depth
        ):
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            text = data.strip()
            if text:
                self.text.append(text)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Scout Route Context four-stage pipeline: input contract, "
            "evidence collection, deterministic compile, and content review."
        )
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--confirm-network-fetch", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--rerun-from",
        choices=("evidence_collection", "deterministic_compile", "content_review"),
        default=None,
    )
    parser.add_argument("--semantic-review-result", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        contract = load_pipeline_contract(args.config)
        result = run_route_context_pipeline(
            contract,
            confirm_network_fetch=args.confirm_network_fetch,
            resume=args.resume,
            rerun_from=args.rerun_from,
            semantic_review_result=args.semantic_review_result,
            dry_run=args.dry_run,
        )
    except PipelineContractError as exc:
        result = {
            "artifact_kind": "pretrip_route_context_pipeline_error",
            "schema_version": SCHEMA_VERSION,
            "status": "contract_error",
            "error": str(exc),
            "boundary": _boundary(),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return {
        "completed": 0,
        "planned": 0,
        "needs_semantic_review": 3,
        "needs_work": 4,
    }.get(str(result.get("status")), 1)


if __name__ == "__main__":
    raise SystemExit(main())
