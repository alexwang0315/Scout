from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from scripts.qualification.enforce_review import enforce_review
from scripts.qualification.evaluate_qualification import evaluate_results
from scripts.qualification.prepare_reviewer_input import build_reviewer_input
from scripts.qualification.run_independent_review import run_review
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Scout Dashboard qualification.")
    parser.add_argument("--scope", choices=("full", "smoke"), default="full")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-review", action="store_true")
    args = parser.parse_args()

    commit_sha = _git_output("rev-parse", "HEAD").strip()
    output_root = (args.output or _default_output(commit_sha)).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"refusing to overwrite qualification packet: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    manifest_path = ROOT / "qualification/dashboard-capability-manifest.yaml"
    schema_path = ROOT / "qualification/schemas/dashboard-capability-manifest.schema.json"
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
            "fixture_provenance": "bounded_synthetic_workspace",
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )

    validation = validate_manifest(manifest_path, schema_path)
    _write_json(output_root / "manifest-validation.json", validation)
    commands: list[dict[str, Any]] = []
    focused_junit = output_root / "junit-focused.xml"
    commands.append(
        _run(
            "focused-pytest",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/qualification/test_dashboard_qualification_bootstrap.py",
                "tests/test_scout_dashboard_page.py",
                "tests/test_dashboard_workspace_publication.py",
                "tests/test_admin_local_raster_tiles.py",
                "tests/test_pretrip_admin_page.py",
                "tests/test_pretrip_admin_api.py",
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
                "tests/test_scout_ai_os_docs.py",
                "tests/test_scout_ai_os_scaffold.py",
                "tests/test_scout_layer_contract.py",
                "tests/test_pretrip_raster_label_adapter.py",
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
    ]
    if args.scope == "smoke":
        browser_command.append("--smoke")
    commands.append(_run("browser-qualification", browser_command, output_root))

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
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    deterministic_pass = validation["valid"] and all(
        command["exit_code"] == 0 for command in commands[:2]
    )
    results["capability_results"][
        "qualification.deterministic_regression_baseline"
    ] = "PASS" if deterministic_pass else "FAIL"
    _write_json(results_path, results)

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    policy = yaml.safe_load(
        (ROOT / "qualification/policies/qualification-gates.yaml").read_text(
            encoding="utf-8"
        )
    )
    machine = evaluate_results(manifest, results["capability_results"], policy)
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
    index = build_index(output_root)
    _write_json(output_root / "evidence-index.json", index)
    reviewer_input = build_reviewer_input(output_root)
    _write_json(output_root / "reviewer-input.json", reviewer_input)

    skip_review = args.skip_review or os.environ.get(
        "SCOUT_QUALIFICATION_SKIP_REVIEW", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    review_gate: dict[str, Any] | None = None
    review_error_type: str | None = None
    if not skip_review:
        try:
            verdict = run_review(
                output_root,
                model=(
                    os.environ.get("SCOUT_QUALIFICATION_REVIEW_MODEL", "").strip()
                    or "gpt-5"
                ),
            )
            _write_json(output_root / "reviewer-verdict.json", verdict)
            review_gate = enforce_review(output_root)
            _write_json(output_root / "merge-gate.json", review_gate)
        except Exception as exc:  # Reviewer absence must fail closed but retain evidence.
            review_error_type = type(exc).__name__
            _write_json(
                output_root / "reviewer-error.json",
                {
                    "schema": "scout.dashboardQualificationReviewerError.v1",
                    "error_type": review_error_type,
                    "summary": "Independent evidence review did not complete.",
                },
            )
    _write_json(output_root / "packet-index.json", build_packet_index(output_root))

    summary = {
        "output_root": str(output_root),
        "commit_sha": commit_sha,
        "scope": args.scope,
        "machine_verdict": machine["machine_verdict"],
        "machine_merge_permitted": machine["merge_permitted"],
        "review_skipped": skip_review,
        "review_merge_permitted": (
            review_gate.get("merge_permitted") if review_gate else None
        ),
        "review_error_type": review_error_type,
        "evidence_root_sha256": index["evidence_root_sha256"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    permitted = machine["merge_permitted"] and (
        skip_review or bool(review_gate and review_gate["merge_permitted"])
    )
    return 0 if permitted else 2


if __name__ == "__main__":
    raise SystemExit(main())
