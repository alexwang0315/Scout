from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ins_dr_field_evidence_check import (  # noqa: E402
    DR_SOURCES,
    GNSS_REANCHOR_SOURCES,
    load_runtime_update_jsonl,
)


def verify_proof_manifest(
    *,
    proof_manifest_path: Path,
    require_reanchor: bool = False,
) -> dict[str, Any]:
    manifest = _load_json_object(proof_manifest_path)
    checks: list[dict[str, Any]] = []
    manifest_dir = proof_manifest_path.parent

    checks.append(
        _check(
            "artifact_kind_is_ins_dr_field_proof_manifest",
            manifest.get("artifact_kind") == "ins_dr_field_proof_manifest",
            "Manifest must be the INS/DR field proof artifact.",
            {"artifact_kind": manifest.get("artifact_kind")},
        )
    )
    checks.append(
        _check(
            "manifest_declares_passed_field_proof",
            manifest.get("field_proof_status") == "passed" and manifest.get("usable_navigation_evidence") is True,
            "Manifest must claim a passed field proof before it can be accepted as completion evidence.",
            {
                "field_proof_status": manifest.get("field_proof_status"),
                "usable_navigation_evidence": manifest.get("usable_navigation_evidence"),
            },
        )
    )
    checks.extend(_verify_boundary(manifest.get("boundary")))
    checks.extend(_verify_file_ref("mission_graph_ref", manifest.get("mission_graph_ref"), manifest_dir))

    input_refs = manifest.get("input_refs")
    if isinstance(input_refs, list) and input_refs:
        for index, ref in enumerate(input_refs):
            checks.extend(_verify_file_ref(f"input_ref_{index}", ref, manifest_dir))
    else:
        checks.append(
            _check(
                "input_refs_present",
                False,
                "Manifest must include at least one input JSONL reference.",
                {"input_refs": input_refs},
            )
        )

    output_refs = manifest.get("output_refs")
    runtime_updates_ref = output_refs.get("runtime_updates_jsonl") if isinstance(output_refs, dict) else None
    field_report_ref = output_refs.get("field_report_json") if isinstance(output_refs, dict) else None
    checks.extend(_verify_file_ref("output_runtime_updates_jsonl", runtime_updates_ref, manifest_dir))
    checks.extend(_verify_file_ref("output_field_report_json", field_report_ref, manifest_dir))

    field_report_path = _resolve_ref_path(field_report_ref, manifest_dir)
    field_report = _load_optional_json_object(field_report_path)
    checks.extend(_verify_field_report(field_report, require_reanchor=require_reanchor))

    runtime_updates_path = _resolve_ref_path(runtime_updates_ref, manifest_dir)
    runtime_updates = _load_optional_runtime_updates(runtime_updates_path)
    checks.extend(_verify_runtime_updates(runtime_updates, require_reanchor=require_reanchor))

    passed = all(check["passed"] for check in checks)
    return {
        "source": "ins_dr_proof_manifest_check",
        "artifact_kind": "ins_dr_proof_manifest_verification",
        "proof_manifest_path": str(proof_manifest_path),
        "proof_manifest_status": "passed" if passed else "failed",
        "completion_ready": passed,
        "require_reanchor": require_reanchor,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_field_proof_manifest_verification_only",
        "checks": checks,
    }


def _verify_boundary(boundary: Any) -> list[dict[str, Any]]:
    expected = {
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_field_proof_manifest_only",
        "live_safety_api_called": False,
        "hardware_control_performed": False,
    }
    checks: list[dict[str, Any]] = []
    for key, expected_value in expected.items():
        actual_value = boundary.get(key) if isinstance(boundary, dict) else None
        checks.append(
            _check(
                f"boundary_{key}",
                actual_value == expected_value,
                "Manifest boundary must preserve offline diagnostic-only proof semantics.",
                {"expected": expected_value, "actual": actual_value},
            )
        )
    return checks


def _verify_file_ref(name: str, ref: Any, manifest_dir: Path) -> list[dict[str, Any]]:
    if not isinstance(ref, dict):
        return [
            _check(
                f"{name}_present",
                False,
                "File reference must be present.",
                {"ref": ref},
            )
        ]

    path = _resolve_ref_path(ref, manifest_dir)
    expected_sha = ref.get("sha256")
    exists = path is not None and path.exists()
    checks = [
        _check(
            f"{name}_exists",
            exists,
            "Referenced file must exist when the proof manifest is verified.",
            {"path": ref.get("path"), "manifest_exists": ref.get("exists"), "resolved_path": str(path) if path else None},
        ),
        _check(
            f"{name}_sha256_recorded",
            isinstance(expected_sha, str) and len(expected_sha) == 64,
            "Referenced file must have a recorded sha256.",
            {"path": ref.get("path"), "sha256": expected_sha},
        ),
    ]
    actual_sha = _sha256_file(path) if exists and path is not None else None
    checks.append(
        _check(
            f"{name}_sha256_matches",
            actual_sha is not None and actual_sha == expected_sha,
            "Referenced file sha256 must match the manifest.",
            {"path": ref.get("path"), "expected_sha256": expected_sha, "actual_sha256": actual_sha},
        )
    )
    return checks


def _verify_field_report(field_report: dict[str, Any] | None, *, require_reanchor: bool) -> list[dict[str, Any]]:
    if field_report is None:
        return [
            _check(
                "field_report_readable_json",
                False,
                "Field report JSON must be readable.",
                None,
            )
        ]

    report_checks = field_report.get("checks")
    failed_report_checks = [
        item.get("name")
        for item in report_checks
        if isinstance(item, dict) and item.get("passed") is not True
    ] if isinstance(report_checks, list) else None
    checks = [
        _check(
            "field_report_declares_passed",
            field_report.get("field_proof_status") == "passed"
            and field_report.get("usable_navigation_evidence") is True,
            "Field report must declare passed usable navigation evidence.",
            {
                "field_proof_status": field_report.get("field_proof_status"),
                "usable_navigation_evidence": field_report.get("usable_navigation_evidence"),
            },
        ),
        _check(
            "field_report_checks_all_passed",
            isinstance(report_checks, list)
            and bool(report_checks)
            and all(isinstance(item, dict) and item.get("passed") is True for item in report_checks),
            "Every field evidence check must pass.",
            {"failed_checks": failed_report_checks, "check_count": len(report_checks) if isinstance(report_checks, list) else None},
        ),
    ]
    if require_reanchor:
        checks.extend(
            [
                _check(
                    "field_report_requires_reanchor",
                    field_report.get("require_reanchor") is True,
                    "Verifier requires a field report that was run with --require-reanchor.",
                    {"require_reanchor": field_report.get("require_reanchor")},
                ),
                _check(
                    "field_report_contains_gnss_reanchor",
                    _as_int(field_report.get("gnss_reanchor_update_count")) > 0,
                    "Field report must include at least one GNSS re-anchor update.",
                    {"gnss_reanchor_update_count": field_report.get("gnss_reanchor_update_count")},
                ),
            ]
        )
    return checks


def _verify_runtime_updates(updates: list[dict[str, Any]] | None, *, require_reanchor: bool) -> list[dict[str, Any]]:
    if updates is None:
        return [
            _check(
                "runtime_updates_readable_jsonl",
                False,
                "Runtime updates JSONL must be readable.",
                None,
            )
        ]

    sources = [_position_source(update) for update in updates]
    checks = [
        _check(
            "runtime_updates_contain_dead_reckoning",
            any(source in DR_SOURCES for source in sources),
            "Runtime updates must include at least one DR estimate.",
            {"sources": sources},
        )
    ]
    if require_reanchor:
        checks.append(
            _check(
                "runtime_updates_contain_gnss_reanchor",
                any(source in GNSS_REANCHOR_SOURCES for source in sources),
                "Runtime updates must include at least one GNSS re-anchor estimate.",
                {"sources": sources},
            )
        )
    return checks


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    return payload


def _load_optional_json_object(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        return _load_json_object(path)
    except Exception:
        return None


def _load_optional_runtime_updates(path: Path | None) -> list[dict[str, Any]] | None:
    if path is None or not path.exists():
        return None
    try:
        return load_runtime_update_jsonl([path])
    except Exception:
        return None


def _resolve_ref_path(ref: Any, manifest_dir: Path) -> Path | None:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not ref["path"]:
        return None
    path = Path(ref["path"])
    if path.is_absolute() or path.exists():
        return path
    candidate = manifest_dir / path
    return candidate if candidate.exists() else path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _position_source(update: dict[str, Any]) -> str | None:
    estimate = update.get("position_estimate")
    if not isinstance(estimate, dict):
        return None
    source = estimate.get("source")
    return str(source) if source not in (None, "") else None


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _check(name: str, passed: bool, reason: str, evidence: Any) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": reason,
        "evidence": evidence,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Scout INS/DR field proof manifest integrity.")
    parser.add_argument("--proof-manifest-json", type=Path, required=True)
    parser.add_argument("--require-reanchor", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = verify_proof_manifest(
            proof_manifest_path=args.proof_manifest_json,
            require_reanchor=args.require_reanchor,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0 if report["completion_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
