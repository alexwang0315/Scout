from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_route_note_candidates import (
    RouteNoteBoundary,
    RouteNoteCandidate,
    RouteNoteCandidateSet,
    RouteNoteCounts,
    build_route_note_candidates_from_gpx,
)
from pretrip_route_note_ln_proposals import (
    RouteNoteLnProposalSet,
    build_route_note_ln_proposals,
)
from pretrip_source_ingest import sha256_file, summarize_gpx


GIS_PERCEPTION_VERSION = "0.1.0"
GIS_PERCEPTION_PROMPT_VERSION = "scout.gis_perception.structured_judgement.v0"
GisAIProviderKind = Literal["pydantic_ai_test", "pydantic_ai_cloud"]
_GIS_PERCEPTION_SYSTEM_PROMPT = """Scout Phase 4 pretrip GIS perception（GIS 感知）structured judgement.
Only judge the route notes provided in the prompt.
Outputs are candidate-only（候選資料）and require human review（人工複核）.
Never claim a runtime safety truth（即時安全事實）or mutate MissionGraph/runtime state.
Use warning_review for collapses/cliffs/danger, hint_review for route-finding hints,
water_or_camp_review for water/camp/shelter notes, and none for mileage-only notes.
"""


class GisPerceptionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _CloudRouteNoteJudgement(GisPerceptionModel):
    source_candidate_id: str
    cp_needed: bool
    checkpoint_type: Literal[
        "none",
        "warning_review",
        "hint_review",
        "water_or_camp_review",
        "landmark_review",
    ]
    suggested_ln_scope: Literal[
        "none",
        "warning_coverage",
        "hint_coverage",
        "review_only",
    ]
    confidence: Literal["low", "medium", "high"]
    stale_risk: Literal["low", "medium", "high"]
    reason_zh: str
    source_signals: tuple[str, ...] = Field(default_factory=tuple)
    human_review_required: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def _enforce_coherence(self) -> "_CloudRouteNoteJudgement":
        if not self.cp_needed:
            if self.checkpoint_type != "none" or self.suggested_ln_scope != "none":
                raise ValueError(
                    "if cp_needed is false, checkpoint_type and suggested_ln_scope must be none"
                )
            return self
        if self.checkpoint_type == "none":
            raise ValueError("if cp_needed is true, checkpoint_type must not be none")
        allowed_scope = {
            "warning_review": {"warning_coverage", "review_only"},
            "hint_review": {"hint_coverage", "review_only"},
            "water_or_camp_review": {"review_only", "none"},
            "landmark_review": {"review_only"},
            "none": {"none"},
        }[self.checkpoint_type]
        if self.suggested_ln_scope not in allowed_scope:
            raise ValueError("suggested_ln_scope must match checkpoint_type")
        return self


class _CloudRouteNoteJudgementBatch(GisPerceptionModel):
    model_role: Literal["route_note_to_cp_intermediary"]
    corpus_boundary: Literal["pretrip_candidate_only"]
    judgements: tuple[_CloudRouteNoteJudgement, ...]

    @model_validator(mode="after")
    def _enforce_unique_ids(self) -> "_CloudRouteNoteJudgementBatch":
        ids = [judgement.source_candidate_id for judgement in self.judgements]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source_candidate_id in cloud GIS judgements")
        return self


class GisPerceptionSourceGpx(GisPerceptionModel):
    source_key: str
    artifact_id: str
    role: Literal["golden_route_reference", "reference_track"]
    uri: str
    sha256: str
    route_name: str
    point_count: int = Field(ge=0)
    route_note_candidate_count: int = Field(ge=0)
    potential_ln_signal_count: int = Field(ge=0)


class GisPerceptionClassifier(GisPerceptionModel):
    classifier_kind: Literal["pydantic_ai_structured_judgement"] = (
        "pydantic_ai_structured_judgement"
    )
    provider_kind: GisAIProviderKind = "pydantic_ai_test"
    model_name: str = "pydantic-ai-test"
    prompt_version: str = GIS_PERCEPTION_PROMPT_VERSION
    prompt_sha256: str
    judgement_count: int = Field(ge=0)
    pydantic_ai_invoked: Literal[True] = True
    live_model_call_performed: bool = False
    network_calls_allowed: bool = False
    pydantic_ai_ready_schema: Literal[True] = True
    notes: tuple[str, ...] = (
        "Pydantic AI（結構化模型判斷器）is the judgement entrypoint; tests use fixture-backed TestModel, alpha runs may use a cloud model.",
    )


class GisPerceptionBoundary(GisPerceptionModel):
    candidate_only: Literal[True] = True
    human_review_required_before_use: Literal[True] = True
    golden_route_is_reference_evidence: Literal[True] = True
    observed_fact_allowed: Literal[False] = False
    derived_measurement_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_gpx_embedded: Literal[False] = False
    live_network_required: Literal[False] = False
    notes: tuple[str, ...] = (
        "GIS Perception（GIS 感知）outputs are pretrip planning candidates only.",
        "Golden route（出發前選定的主參考路線）is not proof that the user has already walked this route.",
    )


class GisPerceptionCounts(GisPerceptionModel):
    source_gpx_count: int = Field(ge=0)
    reference_track_count: int = Field(ge=0)
    gpx_route_note_candidate_count: int = Field(ge=0)
    gpx_potential_ln_signal_count: int = Field(ge=0)
    gpx_ln_proposal_count: int = Field(ge=0)
    checkpoint_candidate_count: int = Field(ge=0)
    warning_review_checkpoint_count: int = Field(ge=0)
    hint_review_checkpoint_count: int = Field(ge=0)
    water_or_camp_review_checkpoint_count: int = Field(ge=0)
    observed_fact_count: Literal[0] = 0
    runtime_mutation_count: Literal[0] = 0
    raw_gpx_payload_count: Literal[0] = 0


class GisPerceptionSourceAttribution(GisPerceptionModel):
    source_kind: Literal[
        "gpx_route_note",
        "overpass_candidate",
        "historical_route_explanation",
    ]
    source_profile: str
    source_candidate_id: str
    source_artifact_id: str
    source_role: str | None = None
    source_label: str
    evidence_type: str
    confidence: Literal["low", "medium", "high"]
    stale_risk: Literal["low", "medium", "high"]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class GisPerceptionCheckpointCandidate(GisPerceptionModel):
    candidate_id: str
    checkpoint_type: Literal[
        "warning_review",
        "hint_review",
        "water_or_camp_review",
    ]
    lat: float
    lon: float
    ele_m: float | None = None
    time: str | None = None
    source_route_note_candidate_id: str
    source_gpx_key: str
    source_gpx_role: Literal["golden_route_reference", "reference_track"]
    source_note_category: Literal[
        "hazard_hint",
        "route_condition_hint",
        "camp_or_water_hint",
    ]
    route_note_age_days: int | None = None
    route_note_freshness: Literal["unknown", "recent", "aging", "stale"] = "unknown"
    stale_route_note: bool = False
    ai_judgement_id: str
    ai_reason_zh: str
    ai_confidence: Literal["low", "medium", "high"]
    ai_stale_risk: Literal["low", "medium", "high"]
    ai_source_signals: tuple[str, ...] = Field(default_factory=tuple)
    linked_ln_proposal_id: str | None = None
    proposed_ln_scope: Literal["warning_coverage", "hint_coverage", "review_only"]
    route_note_summary: str
    recommended_review_action: Literal[
        "review_as_warning_cp",
        "review_as_hint_cp",
        "review_as_water_or_camp_cp",
    ]
    source_attribution: tuple[GisPerceptionSourceAttribution, ...]
    candidate_only: Literal[True] = True
    human_review_required: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    raw_gpx_embedded: Literal[False] = False


class GisPerceptionCandidateSet(GisPerceptionModel):
    artifact_id: str
    artifact_kind: Literal["pretrip_gis_perception_candidates"] = (
        "pretrip_gis_perception_candidates"
    )
    project_id: str
    schema_version: str = GIS_PERCEPTION_VERSION
    status: Literal["candidate_only"] = "candidate_only"
    source_profile: Literal["gpx_corpus_route_notes"] = "gpx_corpus_route_notes"
    source_artifact_id: str
    source_sha256: str
    source_gpx: tuple[GisPerceptionSourceGpx, ...]
    classifier: GisPerceptionClassifier
    counts: GisPerceptionCounts
    boundary: GisPerceptionBoundary = Field(default_factory=GisPerceptionBoundary)
    checkpoint_candidates: tuple[GisPerceptionCheckpointCandidate, ...]
    notes: tuple[str, ...] = (
        "This artifact is the importer-side GPX route-note perception slice; OSM/Overpass tag perception remains a separate evidence source.",
        "Only hazard, route-condition, and camp/water notes become checkpoint candidates in this slice.",
    )

    @model_validator(mode="after")
    def _enforce_counts(self) -> "GisPerceptionCandidateSet":
        checkpoint_types = Counter(candidate.checkpoint_type for candidate in self.checkpoint_candidates)
        if self.counts.source_gpx_count != len(self.source_gpx):
            raise ValueError("source_gpx_count must match source_gpx")
        if self.counts.checkpoint_candidate_count != len(self.checkpoint_candidates):
            raise ValueError("checkpoint_candidate_count must match checkpoint_candidates")
        if self.counts.warning_review_checkpoint_count != checkpoint_types["warning_review"]:
            raise ValueError("warning_review_checkpoint_count must match checkpoint_candidates")
        if self.counts.hint_review_checkpoint_count != checkpoint_types["hint_review"]:
            raise ValueError("hint_review_checkpoint_count must match checkpoint_candidates")
        if (
            self.counts.water_or_camp_review_checkpoint_count
            != checkpoint_types["water_or_camp_review"]
        ):
            raise ValueError("water_or_camp_review_checkpoint_count must match checkpoint_candidates")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class GpxGisPerceptionResult(GisPerceptionModel):
    route_note_candidates: RouteNoteCandidateSet
    gis_perception_ai_judgements: GisPerceptionAIJudgementSet
    route_note_ln_proposals: RouteNoteLnProposalSet
    gis_perception: GisPerceptionCandidateSet


class GisPerceptionAIJudgement(GisPerceptionModel):
    judgement_id: str
    source_candidate_id: str
    source_kind: Literal["gpx_route_note", "overpass_candidate"]
    cp_needed: bool
    checkpoint_type: Literal[
        "none",
        "warning_review",
        "hint_review",
        "water_or_camp_review",
        "poi_review",
        "terrain_review",
    ]
    suggested_ln_scope: Literal[
        "none",
        "warning_coverage",
        "hint_coverage",
        "review_only",
    ]
    confidence: Literal["low", "medium", "high"]
    stale_risk: Literal["low", "medium", "high"]
    reason_zh: str
    source_signals: tuple[str, ...] = Field(default_factory=tuple)
    human_review_required: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def _enforce_scope_coherence(self) -> "GisPerceptionAIJudgement":
        if not self.cp_needed:
            if self.checkpoint_type != "none" or self.suggested_ln_scope != "none":
                raise ValueError(
                    "non-CP GIS judgements must use checkpoint_type=none and suggested_ln_scope=none"
                )
            return self
        if self.checkpoint_type == "none":
            raise ValueError("CP GIS judgements must use a non-none checkpoint_type")
        allowed_scope = {
            "warning_review": {"warning_coverage", "review_only"},
            "hint_review": {"hint_coverage", "review_only"},
            "water_or_camp_review": {"review_only", "none"},
            "poi_review": {"review_only", "none"},
            "terrain_review": {"warning_coverage", "review_only"},
            "none": {"none"},
        }[self.checkpoint_type]
        if self.suggested_ln_scope not in allowed_scope:
            raise ValueError("suggested_ln_scope must match checkpoint_type")
        return self


class GisPerceptionAIJudgementSet(GisPerceptionModel):
    artifact_kind: Literal["pretrip_gis_perception_ai_judgements"] = (
        "pretrip_gis_perception_ai_judgements"
    )
    schema_version: str = GIS_PERCEPTION_VERSION
    prompt_version: str = GIS_PERCEPTION_PROMPT_VERSION
    provider_kind: GisAIProviderKind
    model_name: str
    source_profile: str
    prompt_sha256: str
    input_count: int = Field(ge=0)
    judgement_count: int = Field(ge=0)
    pydantic_ai_invoked: Literal[True] = True
    live_model_call_performed: bool
    network_calls_allowed: bool
    raw_model_output_embedded: Literal[False] = False
    judgements: tuple[GisPerceptionAIJudgement, ...]

    @model_validator(mode="after")
    def _enforce_judgement_count(self) -> "GisPerceptionAIJudgementSet":
        if self.judgement_count != len(self.judgements):
            raise ValueError("judgement_count must match judgements")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class GisPerceptionAIProvider(Protocol):
    provider_kind: GisAIProviderKind
    model_name: str
    live_model_call_performed: bool
    network_calls_allowed: bool

    def judge_route_notes(
        self,
        candidates: Sequence[RouteNoteCandidate],
    ) -> GisPerceptionAIJudgementSet:
        ...

    def judge_overpass_candidates(
        self,
        candidates: Sequence[Any],
    ) -> GisPerceptionAIJudgementSet:
        ...


class PydanticAITestGisPerceptionProvider:
    provider_kind: GisAIProviderKind = "pydantic_ai_test"
    model_name = "pydantic-ai-test"
    live_model_call_performed = False
    network_calls_allowed = False

    def judge_route_notes(
        self,
        candidates: Sequence[RouteNoteCandidate],
    ) -> GisPerceptionAIJudgementSet:
        output = self._run_test_agent(candidates)
        judgement_by_id = {
            judgement.source_candidate_id: judgement
            for judgement in output.judgements
        }
        judgements = tuple(
            _route_note_judgement_from_output(
                index,
                candidate,
                judgement_by_id[candidate.candidate_id],
                provider_suffix="test",
            )
            for index, candidate in enumerate(candidates)
            if candidate.candidate_id in judgement_by_id
        )
        return GisPerceptionAIJudgementSet(
            provider_kind=self.provider_kind,
            model_name=self.model_name,
            source_profile="gpx_route_notes",
            prompt_sha256=_route_note_prompt_sha256(candidates),
            input_count=len(candidates),
            judgement_count=len(judgements),
            live_model_call_performed=self.live_model_call_performed,
            network_calls_allowed=self.network_calls_allowed,
            judgements=judgements,
        )

    def _run_test_agent(
        self,
        candidates: Sequence[RouteNoteCandidate],
    ) -> _CloudRouteNoteJudgementBatch:
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        payload = {
            "model_role": "route_note_to_cp_intermediary",
            "corpus_boundary": "pretrip_candidate_only",
            "judgements": [
                _test_route_note_output(candidate).model_dump(mode="json")
                for candidate in candidates
            ],
        }
        agent = Agent(
            TestModel(custom_output_args=payload, model_name=self.model_name),
            output_type=_CloudRouteNoteJudgementBatch,
            system_prompt=_GIS_PERCEPTION_SYSTEM_PROMPT,
        )
        result = agent.run_sync("fixture-backed route note judgement")
        output = getattr(result, "output", getattr(result, "data", result))
        return _CloudRouteNoteJudgementBatch.model_validate(output)

    def judge_overpass_candidates(
        self,
        candidates: Sequence[Any],
    ) -> GisPerceptionAIJudgementSet:
        return GisPerceptionAIJudgementSet(
            provider_kind=self.provider_kind,
            model_name=self.model_name,
            source_profile="overpass_candidates",
            prompt_sha256=_json_sha256(
                {
                    "prompt_version": GIS_PERCEPTION_PROMPT_VERSION,
                    "candidate_count": len(candidates),
                }
            ),
            input_count=len(candidates),
            judgement_count=0,
            live_model_call_performed=False,
            network_calls_allowed=False,
            judgements=(),
        )


class PydanticAICloudGisPerceptionProvider:
    provider_kind: GisAIProviderKind = "pydantic_ai_cloud"
    live_model_call_performed = True
    network_calls_allowed = True

    def __init__(
        self,
        *,
        model_name: str,
        base_url: str,
        api_key_env: str = "OPENROUTER_API_KEY",
        timeout_seconds: int | None = None,
        max_candidates: int | None = None,
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds or int(
            os.getenv("SCOUT_PRETRIP_GIS_AI_TIMEOUT_SECONDS", "60")
        )
        self.max_candidates = max_candidates or int(
            os.getenv("SCOUT_PRETRIP_GIS_AI_MAX_CANDIDATES", "200")
        )

    def judge_route_notes(
        self,
        candidates: Sequence[RouteNoteCandidate],
    ) -> GisPerceptionAIJudgementSet:
        if len(candidates) > self.max_candidates:
            raise ValueError(
                "cloud GIS judgement input exceeds SCOUT_PRETRIP_GIS_AI_MAX_CANDIDATES; "
                "run a sampled smoke or add an explicit batching policy before full-corpus cloud runs"
            )
        api_key = os.getenv(self.api_key_env) or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                f"missing {self.api_key_env} or OPENAI_API_KEY for cloud GIS judgement"
            )
        prompt_payload = _route_note_prompt_payload(candidates)
        prompt_sha256 = _json_sha256(prompt_payload)
        output = self._run_route_note_agent(prompt_payload, api_key=api_key)
        judgement_by_id = {item.source_candidate_id: item for item in output.judgements}
        judgements = tuple(
            _route_note_judgement_from_output(
                index,
                candidate,
                judgement_by_id[candidate.candidate_id],
                provider_suffix="cloud",
            )
            for index, candidate in enumerate(candidates)
            if candidate.candidate_id in judgement_by_id
        )
        return GisPerceptionAIJudgementSet(
            provider_kind=self.provider_kind,
            model_name=self.model_name,
            source_profile="gpx_route_notes",
            prompt_sha256=prompt_sha256,
            input_count=len(candidates),
            judgement_count=len(judgements),
            live_model_call_performed=True,
            network_calls_allowed=True,
            judgements=judgements,
        )

    def judge_overpass_candidates(
        self,
        candidates: Sequence[Any],
    ) -> GisPerceptionAIJudgementSet:
        raise NotImplementedError(
            "OSM/Overpass tag judgement is reserved for the next GIS perception slice"
        )

    def _run_route_note_agent(
        self,
        prompt_payload: dict[str, Any],
        *,
        api_key: str,
    ) -> "_CloudRouteNoteJudgementBatch":
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            self._run_route_note_agent_blocking,
            prompt_payload,
            api_key,
        )
        try:
            return future.result(timeout=self.timeout_seconds)
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError("cloud GIS Pydantic AI judgement timed out") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_route_note_agent_blocking(
        self,
        prompt_payload: dict[str, Any],
        api_key: str,
    ) -> "_CloudRouteNoteJudgementBatch":
        from pydantic_ai import Agent
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider

        provider = OpenAIProvider(base_url=self.base_url, api_key=api_key)
        agent = Agent(
            OpenAIModel(self.model_name, provider=provider),
            output_type=_CloudRouteNoteJudgementBatch,
            system_prompt=_GIS_PERCEPTION_SYSTEM_PROMPT,
            output_retries=2,
        )
        result = agent.run_sync(
            json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True),
            model_settings={"max_tokens": 5000, "temperature": 0},
        )
        output = getattr(result, "output", getattr(result, "data", result))
        return _CloudRouteNoteJudgementBatch.model_validate(output)


def build_gpx_gis_perception(
    *,
    project_id: str,
    primary_gpx_path: Path | str,
    reference_gpx_paths: list[Path] | tuple[Path, ...],
    primary_artifact_id: str,
    ai_provider: GisPerceptionAIProvider | None = None,
) -> GpxGisPerceptionResult:
    primary_path = Path(primary_gpx_path).expanduser().resolve()
    source_sets: list[tuple[GisPerceptionSourceGpx, RouteNoteCandidateSet]] = []

    source_sets.append(
        _route_note_source(
            project_id=project_id,
            path=primary_path,
            artifact_id=primary_artifact_id,
            source_key="golden_route",
            role="golden_route_reference",
        )
    )
    for index, reference_path in enumerate(sorted(Path(path).expanduser().resolve() for path in reference_gpx_paths), start=1):
        source_sets.append(
            _route_note_source(
                project_id=project_id,
                path=reference_path,
                artifact_id=f"{primary_artifact_id}.reference.{index:03d}",
                source_key=f"reference_{index:03d}_{_safe_key(reference_path.stem)}",
                role="reference_track",
            )
        )

    combined_route_notes = _combined_route_notes(project_id, source_sets)
    resolved_ai_provider = ai_provider or create_gis_perception_ai_provider()
    route_note_judgements = resolved_ai_provider.judge_route_notes(
        combined_route_notes.candidates
    )
    ai_filtered_route_notes = _route_notes_from_ai_judgements(
        combined_route_notes,
        route_note_judgements,
    )
    ln_proposals = build_route_note_ln_proposals(ai_filtered_route_notes)
    gis_perception = _gis_perception_candidate_set(
        project_id=project_id,
        primary_artifact_id=primary_artifact_id,
        source_sets=source_sets,
        route_notes=ai_filtered_route_notes,
        ln_proposals=ln_proposals,
        ai_judgements=route_note_judgements,
    )
    return GpxGisPerceptionResult(
        route_note_candidates=ai_filtered_route_notes,
        gis_perception_ai_judgements=route_note_judgements,
        route_note_ln_proposals=ln_proposals,
        gis_perception=gis_perception,
    )


def gis_perception_to_json(candidate_set: GisPerceptionCandidateSet) -> str:
    return candidate_set.to_json()


def create_gis_perception_ai_provider(
    provider_kind: GisAIProviderKind | None = None,
    *,
    model_name: str | None = None,
    base_url: str | None = None,
    api_key_env: str = "OPENROUTER_API_KEY",
) -> GisPerceptionAIProvider:
    resolved_provider = provider_kind or os.getenv(
        "SCOUT_PRETRIP_GIS_AI_PROVIDER",
        "pydantic_ai_test",
    )
    if resolved_provider == "pydantic_ai_cloud":
        return PydanticAICloudGisPerceptionProvider(
            model_name=model_name
            or os.getenv("SCOUT_PRETRIP_GIS_AI_MODEL")
            or os.getenv("SCOUT_AI_ASSISTANT_MODEL", "google/gemma-4-31b-it"),
            base_url=base_url
            or os.getenv("SCOUT_PRETRIP_GIS_AI_BASE_URL")
            or os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key_env=api_key_env,
        )
    if resolved_provider == "pydantic_ai_test":
        return PydanticAITestGisPerceptionProvider()
    raise ValueError(f"unsupported GIS AI provider: {resolved_provider}")


def _route_note_source(
    *,
    project_id: str,
    path: Path,
    artifact_id: str,
    source_key: str,
    role: Literal["golden_route_reference", "reference_track"],
) -> tuple[GisPerceptionSourceGpx, RouteNoteCandidateSet]:
    notes = build_route_note_candidates_from_gpx(
        path,
        project_id=project_id,
        source_artifact_id=artifact_id,
        source_key=source_key,
    )
    summary = summarize_gpx(path, artifact_id)
    source = GisPerceptionSourceGpx(
        source_key=source_key,
        artifact_id=artifact_id,
        role=role,
        uri=path.as_posix(),
        sha256=sha256_file(path),
        route_name=summary.route_name,
        point_count=summary.point_count,
        route_note_candidate_count=notes.counts.note_candidate_count,
        potential_ln_signal_count=notes.counts.potential_ln_signal_count,
    )
    return source, notes


def _combined_route_notes(
    project_id: str,
    source_sets: list[tuple[GisPerceptionSourceGpx, RouteNoteCandidateSet]],
) -> RouteNoteCandidateSet:
    candidates = tuple(
        candidate
        for _, candidate_set in source_sets
        for candidate in candidate_set.candidates
    )
    categories = Counter(candidate.note_category for candidate in candidates)
    return RouteNoteCandidateSet(
        artifact_id=f"route_note_candidates.{project_id}.gpx_corpus.v0",
        project_id=project_id,
        source_artifact_id=f"source.gpx_corpus.{project_id}",
        source_uri=f"gpx_corpus:{len(source_sets)}",
        source_sha256=_corpus_sha256(source for source, _ in source_sets),
        counts=RouteNoteCounts(
            waypoint_count=sum(candidate_set.counts.waypoint_count for _, candidate_set in source_sets),
            note_candidate_count=len(candidates),
            hazard_hint_count=categories["hazard_hint"],
            route_condition_hint_count=categories["route_condition_hint"],
            camp_or_water_hint_count=categories["camp_or_water_hint"],
            landmark_hint_count=categories["landmark_hint"],
            potential_ln_signal_count=sum(1 for candidate in candidates if candidate.potential_ln_signal),
        ),
        boundary=RouteNoteBoundary(
            notes=(
                "GPX waypoint name/cmt/desc fields from the selected corpus are treated as route-note candidates.",
                "This combined artifact stores derived notes only; raw GPX and trkpt payloads are not embedded.",
                "Human review is required before any candidate can become a planning assumption or future Ln expansion.",
            ),
        ),
        candidates=candidates,
        notes=(
            "Combined route notes from golden route（主參考路線）and reference tracks（參考軌跡）.",
            "The golden route is still pretrip reference evidence, not a completed user track.",
        ),
    )


def _gis_perception_candidate_set(
    *,
    project_id: str,
    primary_artifact_id: str,
    source_sets: list[tuple[GisPerceptionSourceGpx, RouteNoteCandidateSet]],
    route_notes: RouteNoteCandidateSet,
    ln_proposals: RouteNoteLnProposalSet,
    ai_judgements: GisPerceptionAIJudgementSet,
) -> GisPerceptionCandidateSet:
    source_by_key = {source.source_key: source for source, _ in source_sets}
    proposal_by_note = {
        proposal.source_route_note_candidate_id: proposal
        for proposal in ln_proposals.proposals
    }
    judgement_by_note = {
        judgement.source_candidate_id: judgement
        for judgement in ai_judgements.judgements
        if judgement.source_kind == "gpx_route_note"
    }
    checkpoints = tuple(
        _checkpoint_candidate(candidate, source_by_key, proposal_by_note, judgement)
        for candidate in route_notes.candidates
        if (
            (judgement := judgement_by_note.get(candidate.candidate_id)) is not None
            and judgement.cp_needed
            and judgement.checkpoint_type
            in {"warning_review", "hint_review", "water_or_camp_review"}
            and candidate.note_category
            in {"hazard_hint", "route_condition_hint", "camp_or_water_hint"}
        )
    )
    checkpoint_types = Counter(candidate.checkpoint_type for candidate in checkpoints)
    return GisPerceptionCandidateSet(
        artifact_id=f"gis_perception.{project_id}.gpx_corpus.v0",
        project_id=project_id,
        source_artifact_id=primary_artifact_id,
        source_sha256=route_notes.source_sha256,
        source_gpx=tuple(source for source, _ in source_sets),
        classifier=GisPerceptionClassifier(
            provider_kind=ai_judgements.provider_kind,
            model_name=ai_judgements.model_name,
            prompt_sha256=ai_judgements.prompt_sha256,
            judgement_count=ai_judgements.judgement_count,
            live_model_call_performed=ai_judgements.live_model_call_performed,
            network_calls_allowed=ai_judgements.network_calls_allowed,
        ),
        counts=GisPerceptionCounts(
            source_gpx_count=len(source_sets),
            reference_track_count=sum(1 for source, _ in source_sets if source.role == "reference_track"),
            gpx_route_note_candidate_count=route_notes.counts.note_candidate_count,
            gpx_potential_ln_signal_count=route_notes.counts.potential_ln_signal_count,
            gpx_ln_proposal_count=ln_proposals.counts.proposal_count,
            checkpoint_candidate_count=len(checkpoints),
            warning_review_checkpoint_count=checkpoint_types["warning_review"],
            hint_review_checkpoint_count=checkpoint_types["hint_review"],
            water_or_camp_review_checkpoint_count=checkpoint_types["water_or_camp_review"],
        ),
        checkpoint_candidates=checkpoints,
    )


def _checkpoint_candidate(
    candidate: RouteNoteCandidate,
    source_by_key: dict[str, GisPerceptionSourceGpx],
    proposal_by_note: dict[str, object],
    judgement: GisPerceptionAIJudgement,
) -> GisPerceptionCheckpointCandidate:
    source_key = _source_key_from_candidate_id(candidate.candidate_id)
    source = source_by_key[source_key]
    proposal = proposal_by_note.get(candidate.candidate_id)
    if judgement.checkpoint_type == "warning_review":
        checkpoint_type = "warning_review"
        recommended_review_action = "review_as_warning_cp"
    elif judgement.checkpoint_type == "hint_review":
        checkpoint_type = "hint_review"
        recommended_review_action = "review_as_hint_cp"
    elif judgement.checkpoint_type == "water_or_camp_review":
        checkpoint_type = "water_or_camp_review"
        recommended_review_action = "review_as_water_or_camp_cp"
    else:
        raise ValueError(f"unsupported GIS checkpoint judgement: {judgement.checkpoint_type}")
    proposed_ln_scope = (
        judgement.suggested_ln_scope
        if judgement.suggested_ln_scope in {"warning_coverage", "hint_coverage", "review_only"}
        else "review_only"
    )

    return GisPerceptionCheckpointCandidate(
        candidate_id=f"gis_cp.{_safe_key(candidate.candidate_id)}",
        checkpoint_type=checkpoint_type,
        lat=candidate.lat,
        lon=candidate.lon,
        ele_m=candidate.ele_m,
        time=candidate.time,
        source_route_note_candidate_id=candidate.candidate_id,
        source_gpx_key=source_key,
        source_gpx_role=source.role,
        source_note_category=candidate.note_category,
        route_note_age_days=candidate.route_note_age_days,
        route_note_freshness=candidate.route_note_freshness,
        stale_route_note=candidate.stale_route_note,
        ai_judgement_id=judgement.judgement_id,
        ai_reason_zh=judgement.reason_zh,
        ai_confidence=judgement.confidence,
        ai_stale_risk=judgement.stale_risk,
        ai_source_signals=_route_note_source_signals(candidate, judgement),
        linked_ln_proposal_id=getattr(proposal, "proposal_id", None),
        proposed_ln_scope=proposed_ln_scope,
        route_note_summary=candidate.normalized_note,
        recommended_review_action=recommended_review_action,
        source_attribution=(
            GisPerceptionSourceAttribution(
                source_kind=judgement.source_kind,
                source_profile="gpx_corpus_route_notes",
                source_candidate_id=candidate.candidate_id,
                source_artifact_id=source.artifact_id,
                source_role=source.role,
                source_label=candidate.normalized_note,
                evidence_type="pretrip_route_note_candidate",
                confidence=judgement.confidence,
                stale_risk=judgement.stale_risk,
            ),
        ),
    )


def _route_notes_from_ai_judgements(
    route_notes: RouteNoteCandidateSet,
    ai_judgements: GisPerceptionAIJudgementSet,
) -> RouteNoteCandidateSet:
    judged_ids = {judgement.source_candidate_id for judgement in ai_judgements.judgements}
    missing_ids = [
        candidate.candidate_id
        for candidate in route_notes.candidates
        if candidate.candidate_id not in judged_ids
    ]
    if missing_ids:
        raise ValueError(
            f"GIS AI judgement missing {len(missing_ids)} route note candidates; "
            f"first missing id: {missing_ids[0]}"
        )
    return route_notes


def _test_route_note_output(
    candidate: RouteNoteCandidate,
) -> _CloudRouteNoteJudgement:
    category = candidate.note_category
    if category == "hazard_hint":
        cp_needed = True
        checkpoint_type = "warning_review"
        suggested_ln_scope = "warning_coverage"
        confidence = "high"
        stale_risk = "medium"
        reason = "路線註記含危險、崩塌、斷崖或架繩語意，適合先形成警告 CP 候選。"
    elif category == "route_condition_hint":
        cp_needed = True
        checkpoint_type = "hint_review"
        suggested_ln_scope = "hint_coverage"
        confidence = "medium"
        stale_risk = "medium"
        reason = "路線註記含上切、下切、腰繞或路徑提示，適合形成路況提示 CP 候選。"
    elif category == "camp_or_water_hint":
        cp_needed = True
        checkpoint_type = "water_or_camp_review"
        suggested_ln_scope = "review_only"
        confidence = "medium"
        stale_risk = "high"
        reason = "水源或營地資訊可能隨季節改變，先保留為需複核 CP 候選。"
    else:
        cp_needed = False
        checkpoint_type = "none"
        suggested_ln_scope = "none"
        confidence = "low"
        stale_risk = "medium"
        reason = "註記不足以形成 CP，只保留為 route note evidence。"
    if candidate.stale_route_note:
        stale_risk = "high"
        reason = f"{reason} 註記時間距今超過五年，需標記為較舊 route note 重新複核。"
    return _CloudRouteNoteJudgement(
        source_candidate_id=candidate.candidate_id,
        cp_needed=cp_needed,
        checkpoint_type=checkpoint_type,
        suggested_ln_scope=suggested_ln_scope,
        confidence=confidence,
        stale_risk=stale_risk,
        reason_zh=reason,
        source_signals=(candidate.note_category, candidate.normalized_note[:80]),
    )


def _route_note_judgement_from_output(
    index: int,
    candidate: RouteNoteCandidate,
    output: _CloudRouteNoteJudgement,
    *,
    provider_suffix: str,
) -> GisPerceptionAIJudgement:
    checkpoint_type: Literal[
        "none",
        "warning_review",
        "hint_review",
        "water_or_camp_review",
        "poi_review",
        "terrain_review",
    ]
    if output.checkpoint_type == "landmark_review":
        checkpoint_type = "poi_review"
    else:
        checkpoint_type = output.checkpoint_type
    return GisPerceptionAIJudgement(
        judgement_id=f"gis_ai_judgement.gpx_route_note.{provider_suffix}.{index:05d}",
        source_candidate_id=candidate.candidate_id,
        source_kind="gpx_route_note",
        cp_needed=output.cp_needed,
        checkpoint_type=checkpoint_type,
        suggested_ln_scope=output.suggested_ln_scope,
        confidence=output.confidence,
        stale_risk=output.stale_risk,
        reason_zh=output.reason_zh,
        source_signals=tuple(output.source_signals),
    )


def _route_note_prompt_payload(candidates: Sequence[RouteNoteCandidate]) -> dict[str, Any]:
    return {
        "task": "Judge GPX route notes as pretrip CP and Ln proposal candidates.",
        "prompt_version": GIS_PERCEPTION_PROMPT_VERSION,
        "boundary": {
            "candidate_only": True,
            "human_review_required": True,
            "runtime_safety_truth": False,
        },
        "checkpoint_type_semantics": {
            "warning_review": "崩塌、斷崖、危險、架繩或需警戒的位置",
            "hint_review": "上切、下切、腰繞、路徑不明或路況提示",
            "water_or_camp_review": "水源、營地、山屋等補給或停留點",
            "landmark_review": "峰頂、鞍部、岔路或明確地標",
            "none": "不足以形成 CP，只保留 route note",
        },
        "samples": [
            {
                "source_candidate_id": candidate.candidate_id,
                "note": candidate.normalized_note,
                "lat": round(candidate.lat, 7),
                "lon": round(candidate.lon, 7),
                "ele_m": candidate.ele_m,
                "time": candidate.time,
                "route_note_age_days": candidate.route_note_age_days,
                "route_note_freshness": candidate.route_note_freshness,
                "stale_route_note": candidate.stale_route_note,
                "source_waypoint_index": candidate.source_waypoint_index,
            }
            for candidate in candidates
        ],
    }


def _route_note_source_signals(
    candidate: RouteNoteCandidate,
    judgement: GisPerceptionAIJudgement,
) -> tuple[str, ...]:
    signals = list(judgement.source_signals)
    freshness_signal = f"route_note_freshness:{candidate.route_note_freshness}"
    if freshness_signal not in signals:
        signals.append(freshness_signal)
    if candidate.stale_route_note and "stale_route_note" not in signals:
        signals.append("stale_route_note")
    return tuple(signals)


def _route_note_prompt_sha256(candidates: Sequence[RouteNoteCandidate]) -> str:
    return _json_sha256(_route_note_prompt_payload(candidates))


def _json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_key_from_candidate_id(candidate_id: str) -> str:
    prefix = "route_note."
    suffix = ".wpt_"
    if not candidate_id.startswith(prefix) or suffix not in candidate_id:
        raise ValueError(f"unexpected route note candidate_id: {candidate_id}")
    return candidate_id[len(prefix) : candidate_id.index(suffix)]


def _corpus_sha256(sources) -> str:
    digest = hashlib.sha256()
    for source in sorted(sources, key=lambda item: item.source_key):
        digest.update(source.source_key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _safe_key(value: str) -> str:
    key = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_").lower()
    return key[:96] or "source"
