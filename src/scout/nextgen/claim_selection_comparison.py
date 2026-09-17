"""Explicit, frozen, aggregate-only cloud comparison for the terrain experiment."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from scout.nextgen.claim_selection_qualification import qualification_scenarios
from scout.nextgen.claim_support import claim_subject_output_type, claim_subject_prompt
from scout.nextgen.intelligence_gateway import IntelligenceRequest

_SUBJECTS = {"ridge_samples": "ridge", "steep_samples": "steep_terrain"}
_NUMERIC_FACTS = frozenset({
    "sample_count", "ridge_sample_count", "missing_geomorphon_count",
    "slope_ge_30_count", "slope_ge_40_count", "max_slope_degrees", "missing_slope_count",
    "controlled_max_age_seconds", "source_ridge_count", "synthetic_alternative_count",
})
_DATE_FACTS = frozenset({"source_generated_at", "qualification_as_of"})


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def comparison_input_audit(request: IntelligenceRequest) -> dict:
    """Review the model projection, not the private source ledger kept in Scout."""
    request = IntelligenceRequest.model_validate(request.model_dump(mode="json"))
    if request.question not in {case.question for case in qualification_scenarios()}:
        raise ValueError("cloud comparison requires an unchanged reviewed question")
    support = request.claim_support
    if support is None or support.schema_version != "scout.claim_support.v1":
        raise ValueError("cloud comparison requires the v1 subject-selection contract")
    names = set()
    for item in (*support.claims, *support.unavailable):
        if _SUBJECTS.get(item.claim_id) != item.kind:
            raise ValueError("cloud comparison contains an unreviewed subject")
        for fact in item.facts:
            names.add(fact.name)
            if fact.name in _DATE_FACTS and isinstance(fact.value, str):
                datetime.fromisoformat(fact.value)
            elif fact.name in _NUMERIC_FACTS and (fact.value is None or type(fact.value) in (int, float)):
                continue
            else:
                raise ValueError("cloud comparison contains an unreviewed fact")
    prompt = claim_subject_prompt(request.question, support)
    schema = claim_subject_output_type(support).model_json_schema()
    from pydantic_ai.profiles.openai import OpenAIJsonSchemaTransformer

    schema_hash = _hash_bytes(json.dumps(schema, sort_keys=True).encode())
    wire_schema = OpenAIJsonSchemaTransformer(schema, strict=True).walk()
    return {
        "schema_version": "scout.claim_selection_comparison_input.v0",
        "model_prompt_sha256": _hash_bytes(prompt.encode()),
        "output_schema_sha256": schema_hash,
        "wire_output_schema_sha256": _hash_bytes(json.dumps(wire_schema, sort_keys=True).encode()),
        "reviewed_fact_names": sorted(names),
        "model_payload": "fixed_question_and_aggregate_subject_rows_only",
        "source_ledger_forwarded_to_model": False,
        "precise_coordinates_forwarded_to_model": False,
        "expected_answers_forwarded_to_model": False,
        "candidate_only": True, "runtime_safety_truth": False,
    }


def authorize_frozen_comparison(
    request: IntelligenceRequest, *, case_id: str, baseline_dir: Path,
    cloud_authorized: bool,
) -> tuple[IntelligenceRequest, dict]:
    """Allow only this explicit experiment; ordinary requests remain local-only."""
    if not cloud_authorized:
        raise ValueError("cloud comparison requires explicit experiment authorization")
    definition_bytes = (baseline_dir / "case-definitions.json").read_bytes()
    definitions = json.loads(definition_bytes)
    if definitions["scenarios"] != [case.model_dump(mode="json") for case in qualification_scenarios()]:
        raise ValueError("comparison question set or expected outcomes changed")
    case = next((case for case in qualification_scenarios() if case.case_id == case_id), None)
    if case is None or request.question != case.question:
        raise ValueError("comparison case identity does not match the frozen question")
    baseline_bytes = (baseline_dir / f"{case_id}.request.json").read_bytes()
    baseline = IntelligenceRequest.model_validate_json(baseline_bytes)
    for field in ("question", "task_type", "workspace_binding", "claim_support", "evidence_refs"):
        if getattr(request, field) != getattr(baseline, field):
            raise ValueError(f"comparison input changed: {field}")
    audit = comparison_input_audit(request)
    if comparison_input_audit(baseline) != audit:
        raise ValueError("comparison model projection changed")
    # This flag describes the reviewed model payload, not the whole Workspace.
    payload = request.model_dump(mode="json")
    payload.update(allow_cloud_escalation=True, privacy_sensitive=False)
    reviewed = IntelligenceRequest.model_validate(payload)
    return reviewed, {
        **audit, "case_id": case_id,
        "baseline_request_sha256": _hash_bytes(baseline_bytes),
        "baseline_definitions_sha256": _hash_bytes(definition_bytes),
        "planned_question_evidence_binding_and_schema_match": True,
        "cloud_comparison_explicitly_authorized": True,
    }
