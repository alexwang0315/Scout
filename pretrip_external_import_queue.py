from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExternalImportSourceKind(StrEnum):
    WEB_REFERENCE = "web_reference"
    ROUTE_PLANNING_REFERENCE = "route_planning_reference"
    COMMUNITY_ARTICLE = "community_article"


class ExternalImportTreatment(StrEnum):
    PLANNING_REFERENCE = "planning_reference"
    MODEL_INTERPRETATION_INPUT = "model_interpretation_input"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class StrictExternalImportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExternalImportRequest(StrictExternalImportModel):
    request_id: str
    source_id: str
    source_kind: ExternalImportSourceKind
    source_url: str
    title: str
    requested_artifact_kind: Literal["planning_reference"] = "planning_reference"
    intended_treatment: tuple[
        Literal[
            "planning_reference",
            "model_interpretation_input",
            "human_review_required",
        ],
        ...
    ]
    review_requirement: Literal["human_review_required"] = "human_review_required"
    status: Literal["pending"] = "pending"
    crawler_enabled: Literal[False] = False
    network_call_count: Literal[0] = 0
    raw_payload_embedded: Literal[False] = False
    observed_fact_candidate: Literal[False] = False
    derived_measurement_candidate: Literal[False] = False
    authoritative_until_reviewed: Literal[False] = False
    artifact_candidate_only: Literal[True] = True
    notes: str = ""

    @model_validator(mode="after")
    def enforce_external_request_boundary(self) -> "ExternalImportRequest":
        required_treatment = (
            "planning_reference",
            "model_interpretation_input",
            "human_review_required",
        )
        if self.intended_treatment != required_treatment:
            raise ValueError("external import requests must remain planning/reference/review candidates")
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("external import requests must point at external HTTP references")
        return self


class ExternalImportQueueCounts(StrictExternalImportModel):
    request_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    crawler_enabled_count: Literal[0] = 0
    network_call_count: Literal[0] = 0
    observed_fact_count: Literal[0] = 0
    raw_payloads_embedded: Literal[False] = False


class ExternalImportQueueBoundary(StrictExternalImportModel):
    no_network: Literal[True] = True
    no_crawler: Literal[True] = True
    fetches_remote_content: Literal[False] = False
    embeds_raw_payloads: Literal[False] = False
    produces_observed_facts: Literal[False] = False
    produces_derived_measurements: Literal[False] = False
    authoritative_without_review: Literal[False] = False
    notes: tuple[str, ...] = Field(default_factory=tuple)


class ExternalImportQueue(StrictExternalImportModel):
    queue_id: str
    artifact_kind: Literal["pretrip_external_import_queue"] = "pretrip_external_import_queue"
    project_id: str
    phase: Literal["Phase 4"] = "Phase 4"
    status: Literal["pending_human_review"] = "pending_human_review"
    requests: tuple[ExternalImportRequest, ...]
    counts: ExternalImportQueueCounts
    boundary: ExternalImportQueueBoundary
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def enforce_queue_boundary(self) -> "ExternalImportQueue":
        source_ids = [request.source_id for request in self.requests]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id values must be unique")
        if self.counts.request_count != len(self.requests):
            raise ValueError("request_count must match requests")
        pending_count = sum(1 for request in self.requests if request.status == "pending")
        if self.counts.pending_count != pending_count:
            raise ValueError("pending_count must match pending requests")
        if self.counts.network_call_count != 0:
            raise ValueError("network call count must remain zero")
        if any(request.crawler_enabled for request in self.requests):
            raise ValueError("crawler must remain disabled for external import requests")
        if any(request.network_call_count != 0 for request in self.requests):
            raise ValueError("external import requests must not make network calls")
        if any(request.raw_payload_embedded for request in self.requests):
            raise ValueError("external import requests must not embed raw payloads")
        if any(request.observed_fact_candidate for request in self.requests):
            raise ValueError("external import requests must not produce ObservedFact candidates")
        if any(request.derived_measurement_candidate for request in self.requests):
            raise ValueError("external URL requests must not produce DerivedMeasurement candidates")
        return self


def build_chilai_external_import_queue() -> ExternalImportQueue:
    requests = (
        ExternalImportRequest(
            request_id="external_import.chilai_nanhua_day1.joyhike_main_site",
            source_id="source.joyhike.main_site",
            source_kind=ExternalImportSourceKind.WEB_REFERENCE,
            source_url="https://joyhike.com/",
            title="Joyhike main site",
            intended_treatment=(
                ExternalImportTreatment.PLANNING_REFERENCE,
                ExternalImportTreatment.MODEL_INTERPRETATION_INPUT,
                ExternalImportTreatment.HUMAN_REVIEW_REQUIRED,
            ),
            notes=(
                "Reference product precedent only. Store as an Artifact/planning reference candidate; "
                "do not treat the site as field truth or fetch it in this slice."
            ),
        ),
        ExternalImportRequest(
            request_id="external_import.chilai_nanhua_day1.joyhike_route_planning_model",
            source_id="source.joyhike.blog",
            source_kind=ExternalImportSourceKind.ROUTE_PLANNING_REFERENCE,
            source_url="https://blog.joyhike.com/2022/05/trailslevel.html",
            title="Joyhike route-planning model blog",
            intended_treatment=(
                ExternalImportTreatment.PLANNING_REFERENCE,
                ExternalImportTreatment.MODEL_INTERPRETATION_INPUT,
                ExternalImportTreatment.HUMAN_REVIEW_REQUIRED,
            ),
            notes=(
                "Planning-method reference only. Any route difficulty or ETA interpretation remains "
                "ModelInterpretation input until human review and deterministic calculation."
            ),
        ),
        ExternalImportRequest(
            request_id="external_import.chilai_nanhua_day1.ptt_sunriver_timing",
            source_id="source.ptt.sunriver_timing",
            source_kind=ExternalImportSourceKind.COMMUNITY_ARTICLE,
            source_url="https://www.ptt.cc/bbs/Hiking/M.1696430399.A.151.html",
            title="PTT Hiking Sunriver timing article",
            intended_treatment=(
                ExternalImportTreatment.PLANNING_REFERENCE,
                ExternalImportTreatment.MODEL_INTERPRETATION_INPUT,
                ExternalImportTreatment.HUMAN_REVIEW_REQUIRED,
            ),
            notes=(
                "Community timing reference only. The queue embeds no article payload and creates no "
                "observed fact or derived measurement until review and deterministic timing work happen elsewhere."
            ),
        ),
    )
    return ExternalImportQueue(
        queue_id="external_import_queue.chilai_nanhua_day1.v0",
        project_id="chilai_nanhua_day1",
        requests=requests,
        counts=ExternalImportQueueCounts(
            request_count=len(requests),
            pending_count=len(requests),
        ),
        boundary=ExternalImportQueueBoundary(
            notes=(
                "Queue models requested imports only; it performs no fetch, crawl, scrape, or snapshot.",
                "Rows are Artifact/planning-reference candidates and model-interpretation inputs.",
                "External references are not authoritative until human review and deterministic calculation.",
            ),
        ),
        notes=(
            "Phase 4 next slice B external import request queue artifact.",
            "This fixture is intentionally URL-only and does not include raw website payloads.",
        ),
    )


def load_external_import_queue(path: Path | str) -> ExternalImportQueue:
    return ExternalImportQueue.model_validate_json(Path(path).read_text(encoding="utf-8"))


def external_import_queue_to_json(queue: ExternalImportQueue) -> str:
    return json.dumps(queue.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
