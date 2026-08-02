from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pretrip_route_context_scout_ai_regenerate import (
    DEFAULT_MODEL_CONFIG,
    DEFAULT_SKILL_PATH,
    DEFAULT_TIMEOUT_SECONDS,
    regenerate_route_context_briefing,
)
from pretrip_route_context_scout_ai_review import run_scout_ai_review


SCHEMA_VERSION = "scout.route_context_quality_cycle.v1"
DEFAULT_MODEL_NAME = "deepseek/deepseek-v3.2"
DEFAULT_BRIEFING_REF = Path("outputs/briefings/route_context_briefing.html")
DEFAULT_EVIDENCE_REF = Path("inputs/route_context_regeneration_evidence.json")
DEFAULT_SEMANTIC_REVIEW_REF = Path(
    "outputs/route_context_pipeline/scout_ai_semantic_review_result.json"
)
REJECTED_BRIEFING_DIR = Path("outputs/briefings/rejected")


class RouteContextQualityCycleError(RuntimeError):
    pass


CycleRunner = Callable[..., dict[str, Any]]


def run_route_context_briefing_quality_cycle(
    *,
    project_root: Path | str,
    evidence_path: Path | str | None = None,
    model_config_path: Path | str = DEFAULT_MODEL_CONFIG,
    skill_path: Path | str = DEFAULT_SKILL_PATH,
    model_name: str = DEFAULT_MODEL_NAME,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    env_file: Path | str | None = None,
    regenerate_runner: CycleRunner = regenerate_route_context_briefing,
    review_runner: CycleRunner = run_scout_ai_review,
) -> dict[str, Any]:
    """Generate, deterministically compile, review, and conditionally publish.

    The generator and reviewer remain separate model calls. The canonical briefing is
    retained only when the independent review returns a hash-bound PASS.
    """

    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise RouteContextQualityCycleError(f"project root not found: {root}")
    project_path = root / "project.json"
    project = _load_json(project_path)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    selected_model = str(model_name).strip()
    if selected_model != DEFAULT_MODEL_NAME:
        raise RouteContextQualityCycleError(
            f"dashboard quality cycle requires {DEFAULT_MODEL_NAME}"
        )

    evidence_ref, resolved_evidence_path = resolve_regeneration_evidence(
        root,
        project=project,
        evidence_path=evidence_path,
    )
    briefing_ref = Path(
        str(project.get("route_context_briefing_ref") or DEFAULT_BRIEFING_REF)
    )
    briefing_path = _safe_project_path(root, briefing_ref)
    baseline_exists = briefing_path.is_file()
    baseline_bytes = briefing_path.read_bytes() if baseline_exists else None
    baseline_sha256 = (
        hashlib.sha256(baseline_bytes).hexdigest()
        if baseline_bytes is not None
        else None
    )

    generation: dict[str, Any] | None = None
    candidate_sha256: str | None = None
    try:
        generation = regenerate_runner(
            project_root=root,
            evidence_path=resolved_evidence_path,
            model_config_path=model_config_path,
            skill_path=skill_path,
            model_name=selected_model,
            timeout_seconds=timeout_seconds,
            env_file=env_file,
        )
        if generation.get("status") != "completed":
            raise RouteContextQualityCycleError(
                "route context generation did not complete"
            )
        editorial_contract = generation.get("editorial_contract")
        if not isinstance(editorial_contract, dict) or editorial_contract.get(
            "status"
        ) != "PASS":
            raise RouteContextQualityCycleError(
                "deterministic editorial contract did not pass"
            )
        generated_ref = Path(str(generation.get("briefing_ref") or briefing_ref))
        generated_path = _safe_project_path(root, generated_ref)
        if generated_path != briefing_path:
            raise RouteContextQualityCycleError(
                "generator wrote a briefing outside the selected canonical ref"
            )
        if not briefing_path.is_file():
            raise RouteContextQualityCycleError(
                "generator did not write the canonical briefing candidate"
            )
        candidate_sha256 = _sha256_file(briefing_path)
        if generation.get("briefing_sha256") != candidate_sha256:
            raise RouteContextQualityCycleError(
                "generated briefing hash does not match the canonical candidate"
            )

        review_result = review_runner(
            project_root=root,
            model_config_path=model_config_path,
            model_name=selected_model,
            timeout_seconds=timeout_seconds,
            env_file=env_file,
        )
        review = _validated_review(
            root,
            project_id=project_id,
            briefing_sha256=candidate_sha256,
            review_result=review_result,
        )
    except Exception as exc:
        if briefing_path.is_file() and _sha256_file(briefing_path) != baseline_sha256:
            _reject_and_restore(
                root,
                briefing_path=briefing_path,
                baseline_bytes=baseline_bytes,
            )
        if isinstance(exc, RouteContextQualityCycleError):
            raise
        raise RouteContextQualityCycleError(
            f"route context quality cycle failed: {type(exc).__name__}: {exc}"
        ) from exc

    canonical_promoted = review["verdict"] == "PASS"
    rejected_candidate_ref: str | None = None
    canonical_briefing_sha256: str | None = candidate_sha256
    if canonical_promoted:
        _record_passed_cycle(
            project_path,
            project=project,
            evidence_ref=evidence_ref,
            briefing_ref=briefing_ref.as_posix(),
            generation=generation,
            review=review,
        )
        status = "completed"
    else:
        rejected_candidate_ref = _reject_and_restore(
            root,
            briefing_path=briefing_path,
            baseline_bytes=baseline_bytes,
        )
        canonical_briefing_sha256 = baseline_sha256
        _record_rejected_cycle(
            project_path,
            project=project,
            evidence_ref=evidence_ref,
            candidate_sha256=candidate_sha256,
            rejected_candidate_ref=rejected_candidate_ref,
            review=review,
            baseline_sha256=baseline_sha256,
            project_root=root,
        )
        status = "needs_work"

    return {
        "artifact_kind": "scout_ai_route_context_quality_cycle",
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "stage": "content_review",
        "project_id": project_id,
        "evidence_ref": evidence_ref,
        "briefing_ref": briefing_ref.as_posix(),
        "briefing_sha256": candidate_sha256,
        "canonical_briefing_sha256": canonical_briefing_sha256,
        "canonical_promoted": canonical_promoted,
        "rejected_candidate_ref": rejected_candidate_ref,
        "stages": [
            {
                "id": "input_contract",
                "label": "輸入契約",
                "status": "completed",
            },
            {
                "id": "evidence_collection",
                "label": "證據收集",
                "status": "completed",
                "mode": "project_bound_regeneration_evidence",
                "evidence_ref": evidence_ref,
            },
            {
                "id": "deterministic_compile",
                "label": "確定性編譯",
                "status": "completed",
                "model_wrote_html": False,
                "editorial_contract": generation["editorial_contract"],
            },
            {
                "id": "content_review",
                "label": "內容審核",
                "status": "completed" if canonical_promoted else "needs_work",
                "reviewer": "scout-ai-cloud",
                "model": review["model"],
            },
        ],
        "generation": _generation_summary(generation),
        "review": review,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "departure_approval": False,
            "model_wrote_html": False,
            "deterministic_compile": True,
            "independent_content_review": True,
        },
    }


def resolve_regeneration_evidence(
    project_root: Path | str,
    *,
    project: dict[str, Any] | None = None,
    evidence_path: Path | str | None = None,
) -> tuple[str, Path]:
    root = Path(project_root).expanduser().resolve()
    resolved_project = project or _load_json(root / "project.json")
    if evidence_path is not None:
        candidate = Path(evidence_path).expanduser()
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        _require_within_project(root, resolved)
        if not resolved.is_file():
            raise RouteContextQualityCycleError(
                f"route context regeneration evidence not found: {resolved}"
            )
        return resolved.relative_to(root).as_posix(), resolved

    configured_ref = resolved_project.get("route_context_regeneration_evidence_ref")
    if configured_ref:
        resolved = _safe_project_path(root, Path(str(configured_ref)))
        if not resolved.is_file():
            raise RouteContextQualityCycleError(
                "project-bound route context regeneration evidence is missing"
            )
        return Path(str(configured_ref)).as_posix(), resolved

    conventional = _safe_project_path(root, DEFAULT_EVIDENCE_REF)
    if conventional.is_file():
        return DEFAULT_EVIDENCE_REF.as_posix(), conventional

    inputs_dir = root / "inputs"
    matches = (
        sorted(inputs_dir.glob("route_context_regeneration_evidence*.json"))
        if inputs_dir.is_dir()
        else []
    )
    matches = [path.resolve() for path in matches if path.is_file()]
    if len(matches) == 1:
        _require_within_project(root, matches[0])
        return matches[0].relative_to(root).as_posix(), matches[0]
    if not matches:
        raise RouteContextQualityCycleError(
            "route context regeneration evidence is missing; prepare and bind one inputs/route_context_regeneration_evidence*.json file"
        )
    raise RouteContextQualityCycleError(
        "multiple route context regeneration evidence files found; set route_context_regeneration_evidence_ref in project.json"
    )


def _validated_review(
    project_root: Path,
    *,
    project_id: str,
    briefing_sha256: str,
    review_result: dict[str, Any],
) -> dict[str, Any]:
    if review_result.get("status") != "completed":
        raise RouteContextQualityCycleError("independent content review did not complete")
    if review_result.get("briefing_sha256") != briefing_sha256:
        raise RouteContextQualityCycleError(
            "review result belongs to another briefing hash"
        )
    semantic_review_ref = str(
        review_result.get("semantic_review_ref") or DEFAULT_SEMANTIC_REVIEW_REF
    )
    semantic_review_path = _safe_project_path(
        project_root,
        Path(semantic_review_ref),
    )
    semantic = _load_json(semantic_review_path)
    if semantic.get("project_id") != project_id:
        raise RouteContextQualityCycleError("semantic review belongs to another project")
    if semantic.get("briefing_sha256") != briefing_sha256:
        raise RouteContextQualityCycleError("semantic review hash binding failed")
    verdict = semantic.get("verdict")
    if verdict not in {"PASS", "NEEDS_WORK"}:
        raise RouteContextQualityCycleError("semantic review verdict is invalid")
    if review_result.get("verdict") != verdict:
        raise RouteContextQualityCycleError("review summary verdict is inconsistent")
    findings = semantic.get("findings") or []
    priority_revisions = semantic.get("priority_revisions") or []
    if not isinstance(findings, list) or not isinstance(priority_revisions, list):
        raise RouteContextQualityCycleError("semantic review findings are invalid")
    if verdict == "NEEDS_WORK" and not findings:
        raise RouteContextQualityCycleError("NEEDS_WORK review has no actionable finding")
    return {
        "verdict": verdict,
        "readability_score": int(semantic.get("readability_score") or 0),
        "summary": str(semantic.get("summary") or ""),
        "findings": findings,
        "priority_revisions": priority_revisions,
        "finding_count": len(findings),
        "model": str(semantic.get("model") or review_result.get("model") or ""),
        "provider": str(
            semantic.get("provider") or review_result.get("provider") or ""
        ),
        "reviewed_at": str(semantic.get("reviewed_at") or ""),
        "review_packet_ref": str(review_result.get("review_packet_ref") or ""),
        "semantic_review_ref": semantic_review_ref,
        "comparison_ref": str(review_result.get("comparison_ref") or ""),
        "comparison_report_ref": str(
            review_result.get("comparison_report_ref") or ""
        ),
        "prior_review_archive_refs": list(
            review_result.get("prior_review_archive_refs") or []
        ),
    }


def _generation_summary(generation: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "model",
        "provider",
        "receipt_ref",
        "editorial_plan_ref",
        "evidence_packet_ref",
        "prompt_sha256",
        "evidence_sha256",
        "usage",
        "model_request_count",
        "editorial_contract",
    )
    return {key: generation[key] for key in keys if key in generation}


def _record_passed_cycle(
    project_path: Path,
    *,
    project: dict[str, Any],
    evidence_ref: str,
    briefing_ref: str,
    generation: dict[str, Any],
    review: dict[str, Any],
) -> None:
    provider = str(generation.get("provider") or "cloud").replace("-", "_")
    updated = {
        **project,
        "route_context_regeneration_evidence_ref": evidence_ref,
        "route_context_briefing_ref": briefing_ref,
        "route_context_briefing_regeneration_ref": generation.get("receipt_ref"),
        "route_context_briefing_regenerated_by": f"scout_ai_{provider}",
        "route_context_briefing_content_review_ref": review["semantic_review_ref"],
        "route_context_briefing_content_review_verdict": "PASS",
        "route_context_briefing_content_reviewed_sha256": generation[
            "briefing_sha256"
        ],
        "route_context_briefing_content_reviewed_at": review["reviewed_at"],
        "route_context_briefing_content_review_model": review["model"],
        "route_context_briefing_last_attempt_review_ref": review[
            "semantic_review_ref"
        ],
        "route_context_briefing_last_attempt_verdict": "PASS",
    }
    _write_json(project_path, updated)


def _record_rejected_cycle(
    project_path: Path,
    *,
    project: dict[str, Any],
    evidence_ref: str,
    candidate_sha256: str,
    rejected_candidate_ref: str,
    review: dict[str, Any],
    baseline_sha256: str | None,
    project_root: Path,
) -> None:
    updated = {
        **project,
        "route_context_regeneration_evidence_ref": evidence_ref,
        "route_context_briefing_last_attempt_review_ref": review[
            "semantic_review_ref"
        ],
        "route_context_briefing_last_attempt_verdict": "NEEDS_WORK",
        "route_context_briefing_last_attempt_sha256": candidate_sha256,
        "route_context_briefing_last_rejected_ref": rejected_candidate_ref,
    }
    prior_review_ref = _matching_prior_pass_review_ref(
        project_root,
        refs=review.get("prior_review_archive_refs") or [],
        baseline_sha256=baseline_sha256,
    )
    if prior_review_ref is not None:
        prior_review = _load_json(project_root / prior_review_ref)
        updated.update(
            {
                "route_context_briefing_content_review_ref": prior_review_ref,
                "route_context_briefing_content_review_verdict": "PASS",
                "route_context_briefing_content_reviewed_sha256": baseline_sha256,
                "route_context_briefing_content_reviewed_at": prior_review.get(
                    "reviewed_at"
                ),
                "route_context_briefing_content_review_model": prior_review.get(
                    "model"
                ),
            }
        )
    _write_json(project_path, updated)


def _matching_prior_pass_review_ref(
    project_root: Path,
    *,
    refs: list[Any],
    baseline_sha256: str | None,
) -> str | None:
    if baseline_sha256 is None:
        return None
    for raw_ref in refs:
        ref = str(raw_ref)
        if not ref.endswith(DEFAULT_SEMANTIC_REVIEW_REF.name):
            continue
        path = _safe_project_path(project_root, Path(ref))
        if not path.is_file():
            continue
        try:
            review = _load_json(path)
        except RouteContextQualityCycleError:
            continue
        if (
            review.get("briefing_sha256") == baseline_sha256
            and review.get("verdict") == "PASS"
        ):
            return ref
    return None


def _reject_and_restore(
    project_root: Path,
    *,
    briefing_path: Path,
    baseline_bytes: bytes | None,
) -> str:
    if not briefing_path.is_file():
        raise RouteContextQualityCycleError(
            "cannot preserve rejected briefing because candidate is missing"
        )
    candidate_bytes = briefing_path.read_bytes()
    candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
    rejected_ref = (
        REJECTED_BRIEFING_DIR
        / f"route_context_briefing.{candidate_sha256[:16]}.html"
    )
    rejected_path = _safe_project_path(project_root, rejected_ref)
    _write_bytes(rejected_path, candidate_bytes)
    if baseline_bytes is None:
        briefing_path.unlink()
    else:
        _write_bytes(briefing_path, baseline_bytes)
    return rejected_ref.as_posix()


def _safe_project_path(project_root: Path, ref: Path) -> Path:
    if ref.is_absolute():
        raise RouteContextQualityCycleError(f"workspace ref must be relative: {ref}")
    resolved = (project_root / ref).resolve()
    _require_within_project(project_root, resolved)
    return resolved


def _require_within_project(project_root: Path, path: Path) -> None:
    root = project_root.resolve()
    if path != root and not path.is_relative_to(root):
        raise RouteContextQualityCycleError(
            f"workspace ref escapes project: {path}"
        )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RouteContextQualityCycleError(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RouteContextQualityCycleError(f"JSON artifact must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_bytes(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
