from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SAFETY_BOUNDARY_TOOL_ID = "scout.ai.safety_boundary.explain.v0"
SAFETY_BOUNDARY_OUTPUT_KIND = "scout_ai_safety_boundary_explainer_tool_output"

SAFETY_ADMISSION_REQUIRED_FIELDS = (
    "candidate_id",
    "risk_source",
    "risk_score",
    "admission_state",
    "persistence_window",
    "evidence_refs",
    "operator_review_status",
    "phase1_safety_decision_change_allowed",
    "remote_outbound_allowed",
    "last_decision_at",
)
SAFETY_ADMISSION_OPTIONAL_FIELDS = (
    "safety_admission_trace_path",
    *SAFETY_ADMISSION_REQUIRED_FIELDS,
)


def explain_scout_safety_boundary(
    project_root: Path | str,
    *,
    query: str = "",
    safety_admission_trace_path: str | None = None,
    candidate_id: str | None = None,
    risk_source: str | None = None,
    risk_score: float | int | str | None = None,
    admission_state: str | None = None,
    persistence_window: str | None = None,
    evidence_refs: list[str] | None = None,
    operator_review_status: str | None = None,
    phase1_safety_decision_change_allowed: bool | None = None,
    remote_outbound_allowed: bool | None = None,
    last_decision_at: str | None = None,
) -> dict[str, Any]:
    """Explain Scout safety/admission boundaries without mutating runtime state."""

    root = Path(project_root)
    project = _load_project(root)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    raw_provided = {
        "candidate_id": candidate_id,
        "risk_source": risk_source,
        "risk_score": risk_score,
        "admission_state": admission_state,
        "persistence_window": persistence_window,
        "evidence_refs": evidence_refs,
        "operator_review_status": operator_review_status,
        "phase1_safety_decision_change_allowed": phase1_safety_decision_change_allowed,
        "remote_outbound_allowed": remote_outbound_allowed,
        "last_decision_at": last_decision_at,
    }
    admission_trace, admission_trace_report = _load_safety_admission_trace(
        root,
        project,
        explicit_path=safety_admission_trace_path,
    )
    provided = {
        field: _first_present(raw_provided.get(field), admission_trace.get(field))
        for field in raw_provided
    }
    missing_fields = [
        field for field in SAFETY_ADMISSION_REQUIRED_FIELDS if _is_missing(provided[field])
    ]
    decision = _safety_boundary_decision(
        provided=provided,
        missing_fields=missing_fields,
    )
    field_answer = _field_answer(decision=decision, missing_fields=missing_fields)
    decision_output = _decision_output(
        decision=decision,
        missing_fields=missing_fields,
        field_answer=field_answer,
    )
    return {
        "tool_id": SAFETY_BOUNDARY_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "explanation_kind": "read_only_safety_boundary",
        "answerability": (
            "safety_boundary_decision_available"
            if not missing_fields
            else "safety_boundary_missing_required_fields"
        ),
        "source_status": _source_status(admission_trace=admission_trace),
        "decision": decision["decision"],
        "decision_output": decision_output,
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "provided_fields": {
            field: value
            for field, value in provided.items()
            if not _is_missing(value)
        },
        "policy": [
            "Candidate/pretrip risk evidence is advisory and cannot be promoted to runtime safety truth by Scout AI.",
            "Ln or Phase 1 safety changes require a separate safety admission state, persistence evidence, and operator/governance checks.",
            "This tool does not call /safety/*, does not mutate Phase 1 L0-L4 state, and does not send outbound messages.",
        ],
        "next_required_evidence": [
            "live navigation state when the question is about current position or current risk",
            "candidate/admission state proving whether the risk candidate entered safety admission",
            "operator review status and no-mutation proof before any safety-impacting interpretation",
        ],
        "safety_boundary": {
            "role": "Safety Boundary / Runtime Admission Guard",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "decision": decision["decision"],
            "decision_output": decision_output,
            "admission_state": provided.get("admission_state"),
            "operator_review_status": provided.get("operator_review_status"),
            "phase1_safety_decision_change_allowed": (
                provided.get("phase1_safety_decision_change_allowed")
            ),
            "remote_outbound_allowed": provided.get("remote_outbound_allowed"),
            "next_action": decision["next_action"],
        },
        "result_count": 1,
        "results": [
            {
                "label": "safety/admission boundary explainer",
                "decision": decision["decision"],
                "answerability": (
                    "safety_boundary_decision_available"
                    if not missing_fields
                    else "safety_boundary_missing_required_fields"
                ),
                "field_answer": field_answer,
                "decision_output": decision_output,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "snippet": (
                    "must not mutate /safety/* or send outbound; missing_fields="
                    + ",".join(missing_fields)
                ),
            }
        ],
        "source_report": [
            *admission_trace_report,
            {
                "source_kind": "deterministic_safety_boundary_policy",
                "status": "loaded",
                "source_path": "scout_safety_boundary_tool.explain_scout_safety_boundary",
                "loaded_count": 1,
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 2 safety philosophy",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 required development standards",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "boundary": _closed_boundary(),
    }


def _load_project(root: Path) -> dict[str, Any]:
    path = root / "project.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_safety_admission_trace(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = _candidate_paths(
        root,
        project,
        explicit_path=explicit_path,
        ref_keys=(
            "safety_admission_trace_ref",
            "reviewed_safety_admission_trace_ref",
            "runtime_safety_admission_trace_ref",
        ),
        fallbacks=(
            "outputs/safety_admission_trace.reviewed.json",
            "outputs/runtime_safety_admission_trace.reviewed.json",
        ),
    )
    report: list[dict[str, Any]] = []
    for label, path in candidates:
        if not path.exists():
            report.append(
                {
                    "source_kind": "safety_admission_trace",
                    "status": "missing",
                    "source_path": label,
                    "loaded_count": 0,
                }
            )
            continue
        payload = _load_json_object(path)
        trace = _safety_admission_trace_from_payload(payload)
        if not trace:
            report.append(
                {
                    "source_kind": "safety_admission_trace",
                    "status": "invalid_or_empty",
                    "source_path": label,
                    "loaded_count": 0,
                }
            )
            continue
        report.append(
            {
                "source_kind": "safety_admission_trace",
                "status": "loaded",
                "source_path": label,
                "loaded_count": 1,
                "artifact_kind": payload.get("artifact_kind"),
                "source_status": payload.get("status") or payload.get("source_status"),
            }
        )
        return trace, report
    return {}, report[:2]


def _candidate_paths(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    ref_keys: tuple[str, ...],
    fallbacks: tuple[str, ...],
) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    if explicit_path:
        candidates.append((explicit_path, _project_path(root, explicit_path)))
    for key in ref_keys:
        ref = project.get(key)
        if isinstance(ref, str) and ref.strip():
            candidates.append((ref, _project_path(root, ref)))
    for ref in fallbacks:
        candidates.append((ref, _project_path(root, ref)))
    deduped: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for label, path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append((label, path))
    return deduped


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safety_admission_trace_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    nested = payload.get("safety_admission_trace")
    if not isinstance(nested, dict):
        nested = payload.get("runtime_safety_admission")
    trace_source = nested if isinstance(nested, dict) else payload
    fields = (
        "candidate_id",
        "risk_source",
        "risk_score",
        "admission_state",
        "persistence_window",
        "evidence_refs",
        "operator_review_status",
        "phase1_safety_decision_change_allowed",
        "remote_outbound_allowed",
        "last_decision_at",
    )
    trace = {
        field: trace_source.get(field)
        for field in fields
        if not _is_missing(trace_source.get(field))
    }
    if payload.get("status") and "source_status" not in trace:
        trace["source_status"] = payload.get("status")
    return trace


def _source_status(*, admission_trace: dict[str, Any]) -> str:
    if admission_trace:
        return str(
            admission_trace.get("source_status") or "loaded_safety_admission_trace"
        )
    return "candidate_only"


def _first_present(*values: Any) -> Any:
    for value in values:
        if not _is_missing(value):
            return value
    return None


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


def _safety_boundary_decision(
    *,
    provided: dict[str, object],
    missing_fields: list[str],
) -> dict[str, Any]:
    if missing_fields:
        return {
            "decision": "DELAY",
            "main_reasons": [
                "safety admission evidence is incomplete",
                "candidate evidence cannot change runtime safety truth",
            ],
            "next_action": (
                "collect admission_state, persistence evidence, operator review, "
                "and explicit no-mutation proof before any Ln or outbound action"
            ),
            "action_limit": (
                "do not trigger Ln, /safety/*, SOS, outbound send, or hardware "
                "control from candidate/pretrip evidence"
            ),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }

    admission_state = _normalized(provided.get("admission_state"))
    operator_review_status = _normalized(provided.get("operator_review_status"))
    phase1_allowed = provided.get("phase1_safety_decision_change_allowed") is True
    outbound_allowed = provided.get("remote_outbound_allowed") is True
    risk_score = _float_or_none(provided.get("risk_score"))

    if (
        risk_score is not None
        and risk_score >= 90
        and not _approved(admission_state, operator_review_status)
    ):
        return {
            "decision": "ESCALATE",
            "main_reasons": [
                f"risk_score={risk_score:g} is high",
                "admission or operator approval is not proven",
            ],
            "next_action": (
                "escalate to operator review or the deterministic safety admission "
                "service; this tool must remain read-only"
            ),
            "action_limit": (
                "high-risk candidate evidence may demand attention, but Scout AI "
                "cannot mutate Phase 1 safety state"
            ),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }

    if phase1_allowed or outbound_allowed:
        return {
            "decision": "ESCALATE",
            "main_reasons": [
                "caller supplied a safety mutation or outbound-allowed flag",
                "execution must be handled outside the read-only Scout AI answer path",
            ],
            "next_action": (
                "hand off to the approved safety admission/operator workflow; do "
                "not execute from answer synthesis"
            ),
            "action_limit": (
                "this boundary explainer never grants permission to call /safety/* "
                "or send outbound messages"
            ),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }

    return {
        "decision": "NO_GO",
        "main_reasons": [
            f"admission_state={admission_state or 'unknown'}",
            f"operator_review_status={operator_review_status or 'unknown'}",
        ],
        "next_action": (
            "keep the item as candidate evidence, collect review proof, and rerun "
            "safety admission before any Ln transition"
        ),
        "action_limit": (
            "candidate evidence cannot trigger Ln, /safety/*, SOS, outbound send, "
            "or hardware control"
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _field_answer(
    *,
    decision: dict[str, Any],
    missing_fields: list[str],
) -> str:
    reasons = [str(item) for item in decision.get("main_reasons") or [] if str(item)]
    if missing_fields:
        reasons.append("missing=" + ",".join(missing_fields[:5]))
    return (
        f"Safety boundary decision: {decision['decision']}. "
        f"{'; '.join(reasons[:3])}. "
        f"Next step: {decision['next_action']}. "
        "This is candidate/planning evidence only, not runtime safety truth; it "
        "cannot trigger Ln, /safety/*, SOS, outbound send, or hardware control."
    )


def _decision_output(
    *,
    decision: dict[str, Any],
    missing_fields: list[str],
    field_answer: str,
) -> dict[str, Any]:
    decision_label = str(decision["decision"])
    reasons = [str(item) for item in decision.get("main_reasons") or [] if str(item)]
    if not reasons:
        reasons = ["safety boundary evidence did not expose a reason"]
    uncertainty_notes = _uncertainty_notes(
        decision=decision,
        missing_fields=missing_fields,
    )
    first_layer = {
        "decision": _decision_phrase(decision_label),
        "limit": _limit_phrase(decision),
        "reason": " / ".join(reasons[:2]),
        "nextStep": str(decision["next_action"]),
    }
    second_layer = {
        "details": [
            field_answer,
            str(decision.get("action_limit") or ""),
        ],
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": [
            "Candidate or pretrip risk evidence may still indicate real danger.",
            "Runtime safety truth remains owned by deterministic safety admission.",
            "No /safety/* call, Phase 1 mutation, SOS, outbound send, or hardware control was performed.",
        ],
        "requiredConditions": _required_conditions(missing_fields=missing_fields),
        "alternativeActions": _alternative_actions(decision_label),
    }
    return {
        "role": "Safety Boundary / Runtime Admission Guard",
        "format": "SCOUT_OUTDOOR_AI_AGENT_STANDARD.section16",
        "decisionObjectSchema": "ContextualPermission",
        "text": "\n".join(
            (
                f"[Decision] {first_layer['decision']}",
                f"[Limit] {first_layer['limit']}",
                f"[Reason] {first_layer['reason']}",
                f"[Next Step] {first_layer['nextStep']}",
            )
        ),
        "firstLayer": first_layer,
        "secondLayer": second_layer,
        "action": "runtime_safety_admission",
        "decision": decision_label,
        "allowed": False,
        "locationConstraint": "candidate/pretrip evidence boundary only",
        "mainReasons": reasons[:3],
        "cost": {
            "timeBufferChangeMinutes": 0,
            "retreatImpact": (
                "No route or retreat action may be triggered by this read-only "
                "boundary explainer."
            ),
            "safetyTruthImpact": "No runtime safety truth was created or changed.",
        },
        "nextAction": first_layer["nextStep"],
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": second_layer["residualRisk"],
        "requiredConditions": second_layer["requiredConditions"],
        "alternativeActions": second_layer["alternativeActions"],
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 2 safety philosophy",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 MUST/MUST NOT",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "runtimeSafetyTruth": False,
        "phase1SafetyMutationAllowed": False,
        "liveSafetyApiCallsAllowed": False,
        "outboundSendAllowed": False,
    }


def _decision_phrase(decision: str) -> str:
    if decision == "DELAY":
        return "Hold safety-state changes until admission evidence is complete."
    if decision == "NO_GO":
        return "Do not promote this candidate to Ln or runtime safety state."
    if decision == "ESCALATE":
        return "Escalate to operator or deterministic safety admission."
    return "Hold safety boundary decision."


def _limit_phrase(decision: dict[str, Any]) -> str:
    return str(
        decision.get("action_limit")
        or "do not mutate runtime safety state from Scout AI output"
    )


def _uncertainty_notes(
    *,
    decision: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    notes = [
        "This tool explains boundary policy and does not inspect live /safety/* state.",
        "Model or Scout AI output is not runtime safety truth.",
    ]
    if missing_fields:
        notes.append("Missing fields: " + ", ".join(missing_fields))
    if decision["decision"] == "ESCALATE":
        notes.append("Escalation still requires an approved deterministic workflow.")
    return notes


def _required_conditions(*, missing_fields: list[str]) -> list[str]:
    if missing_fields:
        return [
            "Provide " + ", ".join(missing_fields[:6]),
            "Verify operator review and safety admission outside answer synthesis.",
            "Preserve audit evidence that no Phase 1 state mutation occurred here.",
        ]
    return [
        "Keep operator approval and safety admission evidence attached.",
        "Execute any real safety transition only through deterministic runtime services.",
        "Keep Scout AI answer synthesis read-only.",
    ]


def _alternative_actions(decision: str) -> list[str]:
    if decision == "NO_GO":
        return [
            "keep the risk item as candidate evidence",
            "collect persistence and operator review before admission",
            "ask for an explanation rather than a state transition",
        ]
    if decision == "ESCALATE":
        return [
            "hand off to operator review",
            "run the deterministic safety admission workflow",
            "avoid outbound send until the approved workflow authorizes it",
        ]
    return [
        "collect missing admission evidence",
        "rerun the boundary explanation with reviewed fields",
        "avoid Ln, /safety/*, SOS, outbound, and hardware actions meanwhile",
    ]


def _approved(admission_state: str, operator_review_status: str) -> bool:
    approved_admission = admission_state in {"admitted", "approved", "accepted"}
    approved_operator = operator_review_status in {"approved", "reviewed", "accepted"}
    return approved_admission and approved_operator


def _normalized(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
        "model_output_is_runtime_truth": False,
        "safety_api_called": False,
        "phase1_l0_l4_state_mutated": False,
        "outbound_send_performed": False,
    }
