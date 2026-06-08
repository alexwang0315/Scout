from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlanningSourceTreatment(StrEnum):
    ARTIFACT = "Artifact"
    MODEL_INTERPRETATION = "ModelInterpretation"
    HUMAN_REVIEW = "HumanReview"
    DERIVED_MEASUREMENT = "DerivedMeasurement"


class PlanningSourceKind(StrEnum):
    WEB_REFERENCE = "web_reference"
    COMMUNITY_ARTICLE = "community_article"
    IMAGE_MAP = "image_map"
    LOCAL_DIRECTORY = "local_directory"
    LOCAL_FILE = "local_file"
    FIELD_REFERENCE = "field_reference"


class DeterministicMeasurementCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    method: str
    output_scope: Literal["metadata_only", "candidate_measurement"]
    notes: str = ""


class TimingFitnessCalibrationCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    supported_fields: tuple[str, ...] = Field(default_factory=tuple)
    output_scope: Literal["calibration_inputs_only"] = "calibration_inputs_only"
    requires_human_review: bool = True
    notes: str = ""

    @field_validator("supported_fields")
    @classmethod
    def _reject_eta_fields(cls, fields: tuple[str, ...]) -> tuple[str, ...]:
        eta_fields = [field for field in fields if "eta" in field.lower()]
        if eta_fields:
            raise ValueError(f"timing calibration fields must not compute ETA: {eta_fields}")
        return fields


class PlanningSourceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    label: str
    kind: PlanningSourceKind
    uri: str
    reference_only: bool = True
    fetch_policy: Literal["no_network", "local_reference_only"] = "no_network"
    treatment: tuple[PlanningSourceTreatment, ...]
    human_review_before_accepted_assumptions: bool = True
    accepted_assumption_policy: Literal["human_review_required"] = "human_review_required"
    scout_meaning: str
    supported_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    deterministic_measurements: tuple[DeterministicMeasurementCapability, ...] = Field(default_factory=tuple)
    timing_fitness_calibration: TimingFitnessCalibrationCapability | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _enforce_reference_only_semantics(self) -> PlanningSourceEntry:
        if not self.reference_only:
            raise ValueError("planning source registry entries must be reference-only")
        if not self.human_review_before_accepted_assumptions:
            raise ValueError("accepted planning assumptions require HumanReview first")
        if self.fetch_policy not in {"no_network", "local_reference_only"}:
            raise ValueError("planning source registry must not fetch remote content")
        if PlanningSourceTreatment.HUMAN_REVIEW not in self.treatment:
            raise ValueError("planning source registry entries require HumanReview treatment")
        return self


class PreTripSourceRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str
    project_scope: str
    phase: Literal["Phase 4"] = "Phase 4"
    artifact_kind: Literal["pretrip_source_registry"] = "pretrip_source_registry"
    network_policy: Literal["no_network"] = "no_network"
    observed_fact_policy: Literal["never"] = "never"
    entries: tuple[PlanningSourceEntry, ...]
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_registry(self) -> PreTripSourceRegistry:
        source_ids = [entry.source_id for entry in self.entries]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id values must be unique")
        return self


def build_default_pretrip_source_registry() -> PreTripSourceRegistry:
    return PreTripSourceRegistry(
        registry_id="pretrip_source_registry.phase4.chilai_nanhua_day1.v0",
        project_scope="chilai_nanhua_day1",
        entries=(
            PlanningSourceEntry(
                source_id="source.joyhike.main_site",
                label="Joyhike main route page",
                kind=PlanningSourceKind.WEB_REFERENCE,
                uri="https://www.joyhike.com/",
                treatment=(
                    PlanningSourceTreatment.ARTIFACT,
                    PlanningSourceTreatment.MODEL_INTERPRETATION,
                    PlanningSourceTreatment.HUMAN_REVIEW,
                ),
                scout_meaning="Route-planning reference product context only; do not ingest as field truth.",
                supported_capabilities=("route_reference_indexing", "candidate_checkpoint_context"),
                notes="Stored as a pointer only. No crawler, scraper, or source snapshot is created here.",
            ),
            PlanningSourceEntry(
                source_id="source.joyhike.blog",
                label="Joyhike blog planning references",
                kind=PlanningSourceKind.WEB_REFERENCE,
                uri="https://www.joyhike.com/blog",
                treatment=(
                    PlanningSourceTreatment.ARTIFACT,
                    PlanningSourceTreatment.MODEL_INTERPRETATION,
                    PlanningSourceTreatment.HUMAN_REVIEW,
                ),
                scout_meaning="Narrative route context that may suggest candidate POI or timing questions.",
                supported_capabilities=("route_narrative_context", "candidate_poi_context"),
                notes="Human review is required before converting narrative context into accepted assumptions.",
            ),
            PlanningSourceEntry(
                source_id="source.ptt.sunriver_timing",
                label="PTT Sunriver timing article",
                kind=PlanningSourceKind.COMMUNITY_ARTICLE,
                uri="https://www.ptt.cc/",
                treatment=(
                    PlanningSourceTreatment.ARTIFACT,
                    PlanningSourceTreatment.MODEL_INTERPRETATION,
                    PlanningSourceTreatment.HUMAN_REVIEW,
                ),
                scout_meaning="Community timing reference for later manual calibration discussion.",
                supported_capabilities=("route_guide_timing_context", "fitness_calibration_context"),
                timing_fitness_calibration=TimingFitnessCalibrationCapability(
                    capability_id="calibration.ptt_sunriver_timing_context",
                    supported_fields=(
                        "published_segment_minutes",
                        "reported_pack_weight_class",
                        "reported_team_experience_level",
                        "reported_rest_pattern",
                    ),
                    notes="Supports calibration inputs only; this registry does not produce computed ETA.",
                ),
                notes="Do not promote article claims to accepted assumptions until reviewed.",
            ),
            PlanningSourceEntry(
                source_id="source.g11.image_map",
                label="G11 image-map reference",
                kind=PlanningSourceKind.IMAGE_MAP,
                uri="local://references/g11-image-map",
                fetch_policy="local_reference_only",
                treatment=(
                    PlanningSourceTreatment.ARTIFACT,
                    PlanningSourceTreatment.MODEL_INTERPRETATION,
                    PlanningSourceTreatment.HUMAN_REVIEW,
                ),
                scout_meaning="Image-map context for candidate POI/checkpoint interpretation.",
                supported_capabilities=("image_map_georeference_prompt", "candidate_checkpoint_context"),
                notes="Any georeference or route label interpretation remains a reviewed model interpretation.",
            ),
            PlanningSourceEntry(
                source_id="source.local.gpx_dir",
                label="Local GPX source directory",
                kind=PlanningSourceKind.LOCAL_DIRECTORY,
                uri="local://pretrip/gpx",
                fetch_policy="local_reference_only",
                treatment=(
                    PlanningSourceTreatment.ARTIFACT,
                    PlanningSourceTreatment.DERIVED_MEASUREMENT,
                    PlanningSourceTreatment.HUMAN_REVIEW,
                ),
                scout_meaning="Local GPX files can provide deterministic geometry summaries for planning candidates.",
                supported_capabilities=("route_geometry_summary", "route_distance_measurement"),
                deterministic_measurements=(
                    DeterministicMeasurementCapability(
                        capability_id="measurement.local_gpx.distance_bbox_elevation",
                        method="parse GPX points, sum segment haversine distances, and compute bbox/elevation extrema",
                        output_scope="candidate_measurement",
                    ),
                ),
            ),
            PlanningSourceEntry(
                source_id="source.local.jpg_dir",
                label="Local JPG source directory",
                kind=PlanningSourceKind.LOCAL_DIRECTORY,
                uri="local://pretrip/photos",
                fetch_policy="local_reference_only",
                treatment=(PlanningSourceTreatment.ARTIFACT, PlanningSourceTreatment.HUMAN_REVIEW),
                scout_meaning="Photo references can support manual context review but are not facts by themselves.",
                supported_capabilities=("photo_inventory", "manual_context_review"),
            ),
            PlanningSourceEntry(
                source_id="source.local.dtm_dirs",
                label="Local DTM source directories",
                kind=PlanningSourceKind.LOCAL_DIRECTORY,
                uri="local://pretrip/dtm",
                fetch_policy="local_reference_only",
                treatment=(
                    PlanningSourceTreatment.ARTIFACT,
                    PlanningSourceTreatment.DERIVED_MEASUREMENT,
                    PlanningSourceTreatment.HUMAN_REVIEW,
                ),
                scout_meaning="Local DTM headers and rasters can support deterministic terrain metadata candidates.",
                supported_capabilities=("dtm_header_inventory", "route_dtm_coverage_summary"),
                deterministic_measurements=(
                    DeterministicMeasurementCapability(
                        capability_id="measurement.local_dtm.coverage_bbox",
                        method="parse DTM headers and intersect projected tile bboxes with route bbox",
                        output_scope="candidate_measurement",
                    ),
                ),
            ),
            PlanningSourceEntry(
                source_id="source.comparison.rudy_like_gpx",
                label="Rudy-map-like comparison GPX",
                kind=PlanningSourceKind.LOCAL_FILE,
                uri="local://pretrip/comparison/rudy-like-route.gpx",
                fetch_policy="local_reference_only",
                treatment=(
                    PlanningSourceTreatment.ARTIFACT,
                    PlanningSourceTreatment.DERIVED_MEASUREMENT,
                    PlanningSourceTreatment.MODEL_INTERPRETATION,
                    PlanningSourceTreatment.HUMAN_REVIEW,
                ),
                scout_meaning="Comparison route geometry for side-by-side planning analysis only.",
                supported_capabilities=("route_similarity_measurement", "comparison_only_route_context"),
                deterministic_measurements=(
                    DeterministicMeasurementCapability(
                        capability_id="measurement.comparison_gpx.distance_overlap",
                        method="compare local GPX geometry against primary route geometry",
                        output_scope="candidate_measurement",
                        notes="Comparison output must not be compiled into MissionGraph without review.",
                    ),
                ),
            ),
            PlanningSourceEntry(
                source_id="source.scout_260512.field_refs",
                label="scout_260512 field references",
                kind=PlanningSourceKind.FIELD_REFERENCE,
                uri="repo://tests/fixtures/field_cases/scout_260512_golden.json",
                fetch_policy="local_reference_only",
                treatment=(
                    PlanningSourceTreatment.ARTIFACT,
                    PlanningSourceTreatment.DERIVED_MEASUREMENT,
                    PlanningSourceTreatment.MODEL_INTERPRETATION,
                    PlanningSourceTreatment.HUMAN_REVIEW,
                ),
                scout_meaning="Prior field evidence can seed regression planning questions without mutating field evidence.",
                supported_capabilities=("field_regression_reference", "planned_vs_actual_calibration_context"),
                deterministic_measurements=(
                    DeterministicMeasurementCapability(
                        capability_id="measurement.scout_260512.route_summary_refs",
                        method="read existing fixture summaries and reference deterministic route/map metrics",
                        output_scope="metadata_only",
                    ),
                ),
                timing_fitness_calibration=TimingFitnessCalibrationCapability(
                    capability_id="calibration.scout_260512.planned_vs_actual_context",
                    supported_fields=(
                        "actual_elapsed_minutes",
                        "actual_distance_m",
                        "actual_elevation_gain_m",
                        "device_accuracy_summary",
                    ),
                    notes="Provides calibration context from existing field refs, not a new ETA.",
                ),
            ),
        ),
        notes=(
            "Registry stores source references and treatment only; it does not crawl, fetch, snapshot, or parse remote websites.",
            "Accepted planning assumptions require HumanReview before promotion.",
            "DerivedMeasurement is allowed only for deterministic local calculations; observed-fact treatment is intentionally unsupported.",
            "Timing and fitness fields describe supported calibration inputs only, not computed ETA.",
        ),
    )


def registry_to_json(registry: PreTripSourceRegistry) -> str:
    return json.dumps(registry.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_default_pretrip_source_registry(path: Path | str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(registry_to_json(build_default_pretrip_source_registry()), encoding="utf-8")
