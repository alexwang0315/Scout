from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import yaml

from scripts.qualification.enforce_review import enforce_review
from scripts.qualification.evaluate_qualification import evaluate_results
from scripts.qualification.prepare_reviewer_input import build_reviewer_input
from scripts.qualification.validate_manifest import validate_manifest
from scripts.qualification.verify_evidence import (
    build_index,
    build_packet_index,
    verify_index,
)

ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION_UNTRACKED_SCOPES = (
    ".github/workflows/dashboard-qualification.yml",
    "qualification",
    "scripts/qualification",
    "tests/e2e",
    "tests/qualification/test_dashboard_qualification_bootstrap.py",
)
PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def _normalize_runtime_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("qualification requires an explicit http(s) runtime URL")
    if parsed.username or parsed.password:
        raise RuntimeError("qualification runtime URL must not contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise RuntimeError("qualification runtime URL must be an origin without path/query/fragment")
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"{parsed.scheme}://{host}:{port}"


def _runtime_inputs(args: argparse.Namespace) -> tuple[str, str]:
    runtime_url = _normalize_runtime_url(
        str(args.runtime_url or os.environ.get("SCOUT_QUALIFICATION_RUNTIME_URL") or "")
    )
    project_id = str(
        args.project_id or os.environ.get("SCOUT_QUALIFICATION_PROJECT_ID") or ""
    ).strip()
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise RuntimeError("qualification requires an explicit valid real runtime project ID")
    return runtime_url, project_id


def _runtime_probe(runtime_url: str, project_id: str, phase: str) -> dict[str, Any]:
    target = f"{runtime_url}/admin/dashboard?projectId={project_id}"
    request = Request(target, headers={"Cache-Control": "no-store"})
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - explicit operator URL
            body = response.read()
            status = int(response.status)
    except Exception as exc:
        raise RuntimeError(
            f"real runtime Dashboard is unavailable during {phase}: {type(exc).__name__}"
        ) from exc
    if status != 200 or b"Scout Dashboard" not in body:
        raise RuntimeError(f"real runtime Dashboard attestation failed during {phase}")
    parsed = urlsplit(runtime_url)
    listener_pid = None
    local_listener_pid_required = parsed.hostname in {
        "127.0.0.1",
        "localhost",
        "::1",
    }
    if local_listener_pid_required:
        try:
            listener = subprocess.run(
                [
                    "lsof",
                    "-nP",
                    f"-iTCP:{parsed.port}",
                    "-sTCP:LISTEN",
                    "-t",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            pids = sorted(value for value in listener.stdout.split() if value)
            if len(pids) == 1:
                listener_pid = pids[0]
        except OSError:
            listener_pid = None
    return {
        "phase": phase,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "runtime_base_url": runtime_url,
        "runtime_port": parsed.port,
        "project_id": project_id,
        "dashboard_http_status": status,
        "dashboard_html_sha256": hashlib.sha256(body).hexdigest(),
        "local_listener_pid": listener_pid,
        "local_listener_pid_required": local_listener_pid_required,
    }


def _run(
    name: str,
    command: list[str],
    output_root: Path,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path = output_root / "commands" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(completed.stdout, encoding="utf-8")
    return {
        "name": name,
        "argv": command,
        "exit_code": completed.returncode,
        "log_ref": log_path.relative_to(output_root).as_posix(),
    }


def _default_output(commit_sha: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    configured = os.environ.get("SCOUT_QUALIFICATION_OUTPUT")
    if configured:
        return Path(configured).expanduser().resolve()
    return ROOT / "artifacts/qualification/runs" / f"{commit_sha[:12]}-{timestamp}"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git_output(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    ).stdout


def _worktree_patch() -> str:
    sections = [_git_output("diff", "--binary", "HEAD", "--")]
    untracked = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            *QUALIFICATION_UNTRACKED_SCOPES,
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    ).stdout
    for encoded_path in untracked.split(b"\0"):
        if not encoded_path:
            continue
        relative_path = encoded_path.decode("utf-8")
        candidate = ROOT / relative_path
        if not candidate.is_file():
            continue
        patch = subprocess.run(
            [
                "git",
                "diff",
                "--binary",
                "--no-index",
                "--",
                "/dev/null",
                relative_path,
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        ).stdout
        sections.append(patch)
    return "".join(sections)


def _trusted_baseline(current_output: Path) -> Path | None:
    qualification_root = ROOT / "artifacts" / "qualification"
    if not qualification_root.is_dir():
        return None
    verdict_paths = sorted(
        qualification_root.rglob("reviewer-verdict.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for verdict_path in verdict_paths:
        packet_root = verdict_path.parent.resolve()
        if packet_root == current_output.resolve():
            continue
        try:
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
            if verdict.get("verdict") != "QUALIFIED":
                continue
            if verdict.get("review_channel") != "gpt-pro-collaboration-in-app-browser":
                continue
            attestation_path = packet_root / "runtime-attestation.json"
            if not attestation_path.is_file():
                continue
            attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
            if attestation.get("runtime_provenance") != "live_operational_dashboard":
                continue
            if attestation.get("continuity_verified") is not True:
                continue
            if attestation.get("runner_started_runtime") is not False:
                continue
            verification = verify_index(
                packet_root,
                packet_root / "evidence-index.json",
            )
            if not verification["valid"]:
                continue
            if (
                verdict.get("evidence_root_sha256")
                != verification["evidence_root_sha256"]
            ):
                continue
            if not (packet_root / "results.json").is_file():
                continue
            if enforce_review(packet_root).get("merge_permitted") is not True:
                continue
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        return packet_root
    return None


def _delta_state(previous: str | None, current: str) -> str:
    if previous is None:
        return "NEW_CAPABILITY"
    if previous == "PASS" and current == "PASS":
        return "UNCHANGED_PASS"
    if previous == "PASS" and current == "FLAKY":
        return "NEW_FLAKY"
    if previous == "PASS" and current in {
        "FAIL",
        "BLOCKED",
        "INSUFFICIENT_EVIDENCE",
    }:
        return "NEW_REGRESSION"
    if previous != "PASS" and current == "PASS":
        return "RESOLVED_SINCE_BASELINE"
    if previous == current:
        return "UNCHANGED_NON_PASS"
    return "SEMANTIC_DRIFT"


def _build_regression_delta(
    output_root: Path,
    *,
    commit_sha: str,
    capability_results: dict[str, str],
) -> dict[str, Any]:
    baseline_root = _trusted_baseline(output_root)
    baseline_results: dict[str, str] = {}
    baseline_commit_sha = None
    baseline_evidence_root_sha256 = None
    if baseline_root is not None:
        baseline_payload = json.loads(
            (baseline_root / "results.json").read_text(encoding="utf-8")
        )
        baseline_results = dict(baseline_payload.get("capability_results") or {})
        baseline_commit_sha = baseline_payload.get("commit_sha")
        baseline_index = json.loads(
            (baseline_root / "evidence-index.json").read_text(encoding="utf-8")
        )
        baseline_evidence_root_sha256 = baseline_index.get(
            "evidence_root_sha256"
        )
    capability_ids = sorted(set(baseline_results) | set(capability_results))
    return {
        "schema": "scout.dashboardQualificationRegressionDelta.v1",
        "current_commit_sha": commit_sha,
        "baseline_status": (
            "VERIFIED_QUALIFIED_BASELINE"
            if baseline_root is not None
            else "NO_TRUSTED_BASELINE"
        ),
        "baseline_commit_sha": baseline_commit_sha,
        "baseline_evidence_root_sha256": baseline_evidence_root_sha256,
        "capability_deltas": [
            {
                "capability_id": capability_id,
                "baseline_state": baseline_results.get(capability_id),
                "current_state": capability_results.get(
                    capability_id,
                    "INSUFFICIENT_EVIDENCE",
                ),
                "delta": _delta_state(
                    baseline_results.get(capability_id),
                    capability_results.get(
                        capability_id,
                        "INSUFFICIENT_EVIDENCE",
                    ),
                ),
            }
            for capability_id in capability_ids
        ],
    }


def _qualification_test_paths(scope: str) -> dict[str, tuple[str, ...]]:
    guard = {
        "focused": (
            "tests/qualification/test_dashboard_qualification_bootstrap.py",
        ),
        "package": ("tests/test_scout_layer_contract.py",),
    }
    if scope != "legacy-full":
        return guard
    return {
        "focused": (
            *guard["focused"],
            "tests/test_scout_dashboard_page.py",
            "tests/test_dashboard_workspace_publication.py",
            "tests/test_admin_local_raster_tiles.py",
            "tests/test_pretrip_admin_page.py",
            "tests/test_pretrip_admin_api.py",
        ),
        "package": (
            "tests/test_scout_ai_os_docs.py",
            "tests/test_scout_ai_os_scaffold.py",
            *guard["package"],
            "tests/test_pretrip_raster_label_adapter.py",
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Scout Dashboard qualification.")
    parser.add_argument(
        "--scope",
        choices=("guard", "legacy-full", "smoke"),
        default="guard",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runtime-url")
    parser.add_argument("--project-id")
    args = parser.parse_args()
    runtime_url, runtime_project_id = _runtime_inputs(args)

    commit_sha = _git_output("rev-parse", "HEAD").strip()
    output_root = (args.output or _default_output(commit_sha)).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"refusing to overwrite qualification packet: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    round_runtime_initial = _runtime_probe(
        runtime_url,
        runtime_project_id,
        "qualification_round_initial",
    )

    manifest_path = ROOT / "qualification/dashboard-capability-manifest.yaml"
    schema_path = ROOT / "qualification/schemas/dashboard-capability-manifest.schema.json"
    action_contract = json.loads(
        (ROOT / "qualification/dashboard-browser-action-contract.json").read_text(
            encoding="utf-8"
        )
    )
    regression_guard = action_contract["regression_guard"]
    paused_legacy_map_contract = action_contract["paused_legacy_map_contract"]
    shutil.copyfile(manifest_path, output_root / "manifest.snapshot.yaml")
    (output_root / "git-diff.patch").write_text(
        _worktree_patch(),
        encoding="utf-8",
    )
    _write_json(
        output_root / "environment.json",
        {
            "schema": "scout.dashboardQualificationEnvironment.v1",
            "platform": platform.platform(),
            "python": platform.python_version(),
            "scope": args.scope,
            "qualification_boundary": (
                "maplibre_pre_migration_regression_guard"
            ),
            "productization": False,
            "runtime_provenance": "live_operational_dashboard",
            "runtime_base_url": runtime_url,
            "runtime_project_id": runtime_project_id,
            "runner_started_runtime": False,
            "official_qualification_requires_continuity": True,
            "qualification_contract_tests_are_dashboard_evidence": False,
            "dashboard_feature_evidence_requires_live_browser_operation": True,
            "candidate_findings_only": True,
            "runtime_safety_truth": False,
        },
    )

    validation = validate_manifest(manifest_path, schema_path)
    _write_json(output_root / "manifest-validation.json", validation)
    commands: list[dict[str, Any]] = []
    test_paths = _qualification_test_paths(args.scope)
    focused_junit = output_root / "junit-focused.xml"
    commands.append(
        _run(
            "focused-pytest",
            [
                sys.executable,
                "-m",
                "pytest",
                *test_paths["focused"],
                "-q",
                f"--junitxml={focused_junit}",
            ],
            output_root,
        )
    )
    package_junit = output_root / "junit-package.xml"
    commands.append(
        _run(
            "repository-package-pytest",
            [
                sys.executable,
                "-m",
                "pytest",
                *test_paths["package"],
                "-q",
                f"--junitxml={package_junit}",
            ],
            output_root,
        )
    )
    browser_command = [
        "node",
        "scripts/qualification/run_browser_qualification.js",
        f"--output={output_root}",
        f"--runtime-url={runtime_url}",
        f"--project-id={runtime_project_id}",
    ]
    browser_command.append("--prepared-output-root")
    if args.scope == "smoke":
        browser_command.append("--smoke")
    elif args.scope == "legacy-full":
        browser_command.append("--legacy-full")
    commands.append(_run("browser-qualification", browser_command, output_root))
    round_runtime_final: dict[str, Any] | None = None
    round_runtime_final_error: str | None = None
    try:
        round_runtime_final = _runtime_probe(
            runtime_url,
            runtime_project_id,
            "qualification_round_final",
        )
    except Exception as exc:
        round_runtime_final_error = type(exc).__name__

    results_path = output_root / "results.json"
    if results_path.is_file():
        results = json.loads(results_path.read_text(encoding="utf-8"))
    else:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        results = {
            "schema": "scout.dashboardBrowserQualification.v1",
            "commit_sha": commit_sha,
            "scope": args.scope,
            "capability_results": {
                capability["id"]: "INSUFFICIENT_EVIDENCE"
                for surface in manifest["surfaces"]
                for capability in surface["capabilities"]
            },
            "results": [],
            "runtime_provenance": "live_operational_dashboard",
            "runtime_base_url": runtime_url,
            "runtime_project_id": runtime_project_id,
            "runtime_continuity_verified": False,
            "runner_started_runtime": False,
            "official_qualification_eligible": False,
            "contract_tests_are_dashboard_evidence": False,
            "live_browser_counts": {
                "required_routes": len(regression_guard["major_routes"]),
                "required_map_surfaces": 1,
                "required_map_gestures_per_surface": 0,
                "paused_legacy_map_surfaces": len(
                    paused_legacy_map_contract["map_surfaces"]
                ),
                "paused_legacy_map_gestures_per_surface": len(
                    paused_legacy_map_contract["required_map_gestures"]
                ),
                "discovered_controls": 0,
                "map_surface_results": 0,
                "layer_results": 0,
                "visual_checkpoints": 0,
            },
            "candidate_findings_only": True,
            "runtime_safety_truth": False,
        }
    deterministic_pass = validation["valid"] and all(
        command["exit_code"] == 0 for command in commands[:2]
    )
    results["capability_results"][
        "qualification.deterministic_regression_baseline"
    ] = "PASS" if deterministic_pass else "FAIL"
    pid_stable = bool(
        round_runtime_final
        and (
            not round_runtime_initial["local_listener_pid_required"]
            or (
                round_runtime_initial.get("local_listener_pid")
                and round_runtime_final.get("local_listener_pid")
                and round_runtime_initial["local_listener_pid"]
                == round_runtime_final["local_listener_pid"]
            )
        )
    )
    round_continuity_verified = bool(
        round_runtime_final
        and round_runtime_initial["runtime_base_url"]
        == round_runtime_final["runtime_base_url"]
        and round_runtime_initial["project_id"] == round_runtime_final["project_id"]
        and round_runtime_initial["dashboard_html_sha256"]
        == round_runtime_final["dashboard_html_sha256"]
        and pid_stable
    )
    attestation_path = output_root / "runtime-attestation.json"
    if attestation_path.is_file():
        attestation_payload = json.loads(attestation_path.read_text(encoding="utf-8"))
        attestation_payload["qualification_round"] = {
            "initial": round_runtime_initial,
            "final": round_runtime_final,
            "final_probe_error_type": round_runtime_final_error,
            "continuity_verified": round_continuity_verified,
        }
        attestation_payload["continuity_verified"] = bool(
            attestation_payload.get("continuity_verified")
            and round_continuity_verified
        )
        attestation_payload["official_qualification_eligible"] = bool(
            attestation_payload.get("official_qualification_eligible")
            and attestation_payload["continuity_verified"]
        )
        _write_json(attestation_path, attestation_payload)
    results["runtime_continuity_verified"] = bool(
        results.get("runtime_continuity_verified") and round_continuity_verified
    )
    results["official_qualification_eligible"] = bool(
        results.get("official_qualification_eligible")
        and results["runtime_continuity_verified"]
    )
    if not results["runtime_continuity_verified"]:
        results["capability_results"][
            "dashboard.shell.runtime_route_navigation"
        ] = "FAIL"
    _write_json(results_path, results)

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    policy = yaml.safe_load(
        (ROOT / "qualification/policies/qualification-gates.yaml").read_text(
            encoding="utf-8"
        )
    )
    machine = evaluate_results(
        manifest,
        results["capability_results"],
        policy,
        qualification_scope=args.scope,
    )
    machine["commit_sha"] = commit_sha
    _write_json(output_root / "machine-verdict.json", machine)
    _write_json(
        output_root / "regression-delta.json",
        _build_regression_delta(
            output_root,
            commit_sha=commit_sha,
            capability_results=results["capability_results"],
        ),
    )
    _write_json(
        output_root / "build-info.json",
        {
            "schema": "scout.dashboardQualificationBuildInfo.v1",
            "commit_sha": commit_sha,
            "worktree_status": _git_output("status", "--short"),
            "commands": commands,
        },
    )
    candidate_findings_path = output_root / "candidate-findings.json"
    if not candidate_findings_path.is_file():
        _write_json(
            candidate_findings_path,
            {
                "schema": "scout.dashboardQualificationCandidateFindings.v1",
                "findings": [
                    {
                        "candidate_finding_id": "SCOUT-CANDIDATE-0001",
                        "confirmation_state": "AWAITING_LIVE_RUNTIME_EVIDENCE",
                        "issue_record_allowed": False,
                        "finding_kind": "runtime_evidence_unavailable",
                        "capability_id": "dashboard.shell.runtime_route_navigation",
                        "observed_behavior": (
                            "The official live-runtime browser packet was not produced."
                        ),
                        "disposition": "REQUEST_MORE_EVIDENCE",
                    }
                ],
                "confirmation_required_from": (
                    "gpt-pro-collaboration-in-app-browser"
                ),
                "canonical_review_items_written": False,
                "remediation_authorized": False,
                "specification_change_authorized": False,
            },
        )
    index = build_index(output_root)
    _write_json(output_root / "evidence-index.json", index)
    attestation_path = output_root / "runtime-attestation.json"
    runtime_attestation_sha256 = (
        hashlib.sha256(attestation_path.read_bytes()).hexdigest()
        if attestation_path.is_file()
        else None
    )
    review_state = "AWAITING_LIVE_RUNTIME_EVIDENCE"
    reviewer_input_error: str | None = None
    if (
        attestation_path.is_file()
        and results.get("official_qualification_eligible") is True
        and results.get("runtime_continuity_verified") is True
    ):
        try:
            reviewer_input = build_reviewer_input(output_root)
            _write_json(output_root / "reviewer-input.json", reviewer_input)
            review_state = "AWAITING_GPT_PRO_COLLABORATION"
        except Exception as exc:
            reviewer_input_error = type(exc).__name__
            review_state = "INSUFFICIENT_EVIDENCE"
    _write_json(
        output_root / "gpt-pro-review-status.json",
        {
            "schema": "scout.dashboardQualificationGptProReviewStatus.v1",
            "state": review_state,
            "required_channel": "gpt-pro-collaboration-in-app-browser",
            "commit_sha": commit_sha,
            "evidence_root_sha256": index["evidence_root_sha256"],
            "runtime_attestation_sha256": runtime_attestation_sha256,
            "reviewer_input_error_type": reviewer_input_error,
            "final_verdict_available": False,
            "review_items_allowed": False,
            "remediation_authorized": False,
            "specification_change_authorized": False,
            "next_required_action": {
                "AWAITING_LIVE_RUNTIME_EVIDENCE": "Collect valid live-runtime evidence.",
                "AWAITING_GPT_PRO_COLLABORATION": (
                    "Use gpt-pro-collaboration in the Codex in-app browser."
                ),
                "INSUFFICIENT_EVIDENCE": (
                    "Repair the evidence packet without changing product behavior."
                ),
            }[review_state],
        },
    )
    _write_json(output_root / "packet-index.json", build_packet_index(output_root))

    summary = {
        "output_root": str(output_root),
        "commit_sha": commit_sha,
        "scope": args.scope,
        "qualification_contract_tests_are_dashboard_evidence": False,
        "harness_contract_checks": [
            {
                "name": command["name"],
                "exit_code": command["exit_code"],
                "dashboard_feature_evidence": False,
            }
            for command in commands[:2]
        ],
        "live_browser_counts": results.get("live_browser_counts", {}),
        "runtime_base_url": runtime_url,
        "runtime_project_id": runtime_project_id,
        "runtime_attestation_sha256": runtime_attestation_sha256,
        "provisional_machine_verdict": machine["machine_verdict"],
        "machine_merge_permitted": machine["merge_permitted"],
        "review_state": review_state,
        "final_verdict": None,
        "review_merge_permitted": None,
        "human_confirmation_required_after_review": True,
        "remediation_authorized": False,
        "specification_change_authorized": False,
        "evidence_root_sha256": index["evidence_root_sha256"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
