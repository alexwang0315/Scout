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


def explain_scout_safety_boundary(
    project_root: Path | str,
    *,
    query: str = "",
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
    provided = {
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
    missing_fields = [
        field for field in SAFETY_ADMISSION_REQUIRED_FIELDS if _is_missing(provided[field])
    ]
    return {
        "tool_id": SAFETY_BOUNDARY_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "explanation_kind": "read_only_safety_boundary",
        "answerability": "advisory_boundary_explained",
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
        "results": [
            {
                "label": "safety/admission boundary explainer",
                "snippet": (
                    "must not mutate /safety/* or send outbound; missing_fields="
                    + ",".join(missing_fields)
                ),
            }
        ],
        "source_report": [
            {
                "source_kind": "deterministic_safety_boundary_policy",
                "status": "loaded",
                "source_path": "scout_safety_boundary_tool.explain_scout_safety_boundary",
                "loaded_count": 1,
            }
        ],
        "boundary": _closed_boundary(),
    }


def _load_project(root: Path) -> dict[str, Any]:
    path = root / "project.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


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
