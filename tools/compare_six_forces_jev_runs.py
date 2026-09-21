#!/usr/bin/env python3
"""Compare a Six-Forces run with its Jev shadow-advisory counterpart.

The comparison is intentionally read-only.  It uses the evaluator's persisted
verifier and quality labels, and reports Jev telemetry separately so an advisory
call cannot be mistaken for a runtime route or safety decision.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object: {path}")
    return payload


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(key) or "null") for row in rows).items()))


def _nested_status_counts(
    rows: list[dict[str, Any]], parent: str, child: str
) -> dict[str, int]:
    return dict(
        sorted(
            Counter(
                str((row.get(parent) or {}).get(child) or "null")
                for row in rows
                if isinstance(row.get(parent), dict)
            ).items()
        )
    )


def _rate(value: int, total: int) -> float:
    return round(value / total, 6) if total else 0.0


def _delta(new: float | int, old: float | int) -> float | int:
    value = new - old
    return round(value, 6) if isinstance(value, float) else value


def _run_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    accepted = sum(
        1 for row in rows if (row.get("verifier") or {}).get("status") == "pass"
    )
    identity_pass = sum(
        1
        for row in rows
        if (row.get("context_identity_check") or {}).get("status") == "pass"
    )
    quality = _counts(
        [
            {
                "quality": (row.get("answer_quality_screen") or {}).get(
                    "classification"
                )
            }
            for row in rows
        ],
        "quality",
    )
    model_requests = sum(int(row.get("model_request_count") or 0) for row in rows)
    duration_ms = sum(int(row.get("duration_ms") or 0) for row in rows)
    force: dict[str, Any] = {}
    by_force: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_force[str(row.get("force") or "unknown")].append(row)
    for force_code, force_rows in sorted(by_force.items()):
        force_accepted = sum(
            1
            for row in force_rows
            if (row.get("verifier") or {}).get("status") == "pass"
        )
        force[force_code] = {
            "runs": len(force_rows),
            "strict_accepted": force_accepted,
            "strict_acceptance_rate": _rate(force_accepted, len(force_rows)),
            "verifier_status": _nested_status_counts(force_rows, "verifier", "status"),
            "quality": _counts(
                [
                    {
                        "quality": (row.get("answer_quality_screen") or {}).get(
                            "classification"
                        )
                    }
                    for row in force_rows
                ],
                "quality",
            ),
        }
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("question_id") or row.get("run_case_id"))].append(row)
    all_variant_pass = sum(
        1
        for group_rows in groups.values()
        if group_rows
        and all((row.get("verifier") or {}).get("status") == "pass" for row in group_rows)
    )
    return {
        "runs": total,
        "unique_questions": len(groups),
        "strict_accepted": accepted,
        "strict_acceptance_rate": _rate(accepted, total),
        "conservative_question_all_variants_pass": all_variant_pass,
        "conservative_question_rate": _rate(all_variant_pass, len(groups)),
        "verifier_status": _nested_status_counts(rows, "verifier", "status"),
        "identity_status": _nested_status_counts(
            rows, "context_identity_check", "status"
        ),
        "quality": quality,
        "failure_category": _counts(rows, "failure_category"),
        "model_requests": model_requests,
        "mean_model_requests": _rate(model_requests, total),
        "duration_ms_sum": duration_ms,
        "mean_duration_ms": _rate(duration_ms, total),
        "blocking_evidence_gap_rows": sum(
            1 for row in rows if row.get("blocking_missing_evidence")
        ),
        "force": force,
    }


def _jev_metrics(rows: list[dict[str, Any]], events_path: Path) -> dict[str, Any]:
    jev_rows = [row.get("jev_preflight") for row in rows if row.get("jev_preflight")]
    status = Counter(str((item or {}).get("status") or "null") for item in jev_rows)
    ok_rows = [item for item in jev_rows if (item or {}).get("status") == "ok"]
    usages = [item.get("usage") or {} for item in ok_rows]
    guard_counts: Counter[str] = Counter()
    signal_tool: Counter[str] = Counter()
    signal_escalation: Counter[str] = Counter()
    signal_sufficiency: Counter[str] = Counter()
    for item in ok_rows:
        for key, value in (item.get("guards") or {}).items():
            if value is True:
                guard_counts[key] += 1
        signals = item.get("signals") or {}
        if signals.get("tool_family"):
            signal_tool[str(signals["tool_family"])] += 1
        if signals.get("escalation"):
            signal_escalation[str(signals["escalation"])] += 1
        if "evidence_sufficient" in signals:
            signal_sufficiency[str(signals["evidence_sufficient"])] += 1
    event_counts: Counter[str] = Counter()
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = json.loads(line).get("event")
                if event:
                    event_counts[str(event)] += 1
    return {
        "row_count_with_preflight": len(jev_rows),
        "status": dict(sorted(status.items())),
        "successful_calls": len(ok_rows),
        "success_rate": _rate(len(ok_rows), len(jev_rows)),
        "latency_ms_sum": sum(int(item.get("latency_ms") or 0) for item in ok_rows),
        "mean_latency_ms": _rate(
            sum(int(item.get("latency_ms") or 0) for item in ok_rows), len(ok_rows)
        ),
        "usage": {
            "input_tokens": sum(int(item.get("input_tokens") or 0) for item in usages),
            "output_tokens": sum(int(item.get("output_tokens") or 0) for item in usages),
            "cost": round(
                sum(float(item.get("cost") or 0.0) for item in usages), 8
            ),
        },
        "guard_true_counts": dict(sorted(guard_counts.items())),
        "signal_tool_family": dict(sorted(signal_tool.items())),
        "signal_escalation": dict(sorted(signal_escalation.items())),
        "signal_evidence_sufficient": dict(sorted(signal_sufficiency.items())),
        "event_counts": dict(sorted(event_counts.items())),
        "all_candidate_only": all(
            bool((item or {}).get("candidate_only")) for item in jev_rows
        ),
        "all_runtime_safety_truth_false": all(
            (item or {}).get("runtime_safety_truth") is False for item in jev_rows
        ),
    }


def build_comparison(baseline_dir: Path, jev_dir: Path) -> dict[str, Any]:
    baseline_manifest = _read_json(baseline_dir / "run_manifest.json")
    jev_manifest = _read_json(jev_dir / "run_manifest.json")
    baseline_rows = _read_rows(baseline_dir / "per_case_results.jsonl")
    jev_rows = _read_rows(jev_dir / "per_case_results.jsonl")
    baseline = _run_metrics(baseline_rows)
    jev_run = _run_metrics(jev_rows)
    jev = _jev_metrics(jev_rows, jev_dir / "jev-events.jsonl")
    comparison = {
        "schema_version": "scout.ai.six_forces_jev_comparison.v1",
        "baseline": {
            "directory": str(baseline_dir),
            "run_id": baseline_manifest.get("run_id"),
            "manifest": {
                key: baseline_manifest.get(key)
                for key in (
                    "workspace",
                    "scenario_artifact_sha256",
                    "model",
                    "mser_mode",
                    "guided_retry_enabled",
                    "max_model_requests_per_attempt",
                    "workers",
                )
            },
            "metrics": baseline,
        },
        "jev_shadow_run": {
            "directory": str(jev_dir),
            "run_id": jev_manifest.get("run_id"),
            "manifest": {
                key: jev_manifest.get(key)
                for key in (
                    "workspace",
                    "scenario_artifact_sha256",
                    "model",
                    "mser_mode",
                    "guided_retry_enabled",
                    "max_model_requests_per_attempt",
                    "workers",
                    "jev_enabled",
                    "jev_model",
                    "jev_endpoint",
                    "jev_mode",
                )
            },
            "metrics": jev_run,
            "jev": jev,
        },
        "delta_jev_minus_baseline": {
            "strict_accepted": _delta(
                jev_run["strict_accepted"], baseline["strict_accepted"]
            ),
            "strict_acceptance_rate": _delta(
                jev_run["strict_acceptance_rate"], baseline["strict_acceptance_rate"]
            ),
            "conservative_question_all_variants_pass": _delta(
                jev_run["conservative_question_all_variants_pass"],
                baseline["conservative_question_all_variants_pass"],
            ),
            "conservative_question_rate": _delta(
                jev_run["conservative_question_rate"],
                baseline["conservative_question_rate"],
            ),
            "verifier_failures": _delta(
                jev_run["verifier_status"].get("fail", 0),
                baseline["verifier_status"].get("fail", 0),
            ),
            "model_requests": _delta(
                jev_run["model_requests"], baseline["model_requests"]
            ),
            "mean_model_requests": _delta(
                jev_run["mean_model_requests"], baseline["mean_model_requests"]
            ),
            "duration_ms_sum": _delta(
                jev_run["duration_ms_sum"], baseline["duration_ms_sum"]
            ),
            "mean_duration_ms": _delta(
                jev_run["mean_duration_ms"], baseline["mean_duration_ms"]
            ),
        },
        "interpretation": {
            "answer_path_changed_by_jev": False,
            "runtime_route_changed_by_jev": jev["guard_true_counts"].get(
                "runtime_route_changed_by_jev", 0
            ),
            "runtime_authority_granted_by_jev": jev["guard_true_counts"].get(
                "runtime_authority_granted", 0
            ),
            "causal_attribution": (
                "not_identifiable_from_shadow_run_alone; model sampling and worker "
                "schedule remain confounders"
            ),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }
    return comparison


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _table_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"`{key}`={value}" for key, value in counts.items()) or "(none)"


def render_markdown(comparison: dict[str, Any]) -> str:
    base = comparison["baseline"]["metrics"]
    run = comparison["jev_shadow_run"]["metrics"]
    jev = comparison["jev_shadow_run"]["jev"]
    delta = comparison["delta_jev_minus_baseline"]
    lines = [
        "# Six-Forces baseline vs Jev shadow comparison",
        "",
        "This is a read-only comparison. Jev was called as a shadow advisory "
        "preflight; deterministic Scout execution remained authoritative.",
        "",
        "| Metric | No Jev baseline | Jev shadow | Delta |",
        "|---|---:|---:|---:|",
        f"| Expanded runs | {base['runs']} | {run['runs']} | {run['runs'] - base['runs']} |",
        f"| Strict accepted | {base['strict_accepted']} ({base['strict_acceptance_rate']:.2%}) | {run['strict_accepted']} ({run['strict_acceptance_rate']:.2%}) | {delta['strict_accepted']} ({delta['strict_acceptance_rate']:+.2%}) |",
        f"| Conservative all-variants questions | {base['conservative_question_all_variants_pass']} ({base['conservative_question_rate']:.2%}) | {run['conservative_question_all_variants_pass']} ({run['conservative_question_rate']:.2%}) | {delta['conservative_question_all_variants_pass']} ({delta['conservative_question_rate']:+.2%}) |",
        f"| Verifier failures | {base['verifier_status'].get('fail', 0)} | {run['verifier_status'].get('fail', 0)} | {delta['verifier_failures']} |",
        f"| Logical model requests | {base['model_requests']} | {run['model_requests']} | {delta['model_requests']} |",
        f"| Mean run duration (ms) | {base['mean_duration_ms']:.1f} | {run['mean_duration_ms']:.1f} | {delta['mean_duration_ms']:.1f} |",
        "",
        "## Per-force strict acceptance",
        "",
        "| Force | Baseline | Jev shadow | Delta |",
        "|---|---:|---:|---:|",
    ]
    forces = sorted(set(base["force"]) | set(run["force"]))
    for force in forces:
        old = base["force"].get(force, {}).get("strict_accepted", 0)
        new = run["force"].get(force, {}).get("strict_accepted", 0)
        lines.append(f"| {force} | {old} | {new} | {new - old} |")
    lines.extend(
        [
            "",
            "## Jev role and guards",
            "",
            f"- Calls: {jev['successful_calls']}/{jev['row_count_with_preflight']} "
            f"successful ({jev['success_rate']:.2%}); event counts: "
            f"{_table_counts(jev['event_counts'])}.",
            f"- Mean Jev latency: {jev['mean_latency_ms']:.1f} ms; usage: "
            f"{jev['usage']['input_tokens']} input tokens, "
            f"{jev['usage']['output_tokens']} output tokens, "
            f"cost={jev['usage']['cost']:.8f}.",
            f"- Signal tool families: {_table_counts(jev['signal_tool_family'])}; "
            f"escalations: {_table_counts(jev['signal_escalation'])}; "
            f"evidence_sufficient: {_table_counts(jev['signal_evidence_sufficient'])}.",
            f"- True guard counts: {_table_counts(jev['guard_true_counts'])}.",
            f"- Candidate-only preserved for every row: `{jev['all_candidate_only']}`; "
            f"runtime_safety_truth false for every row: `{jev['all_runtime_safety_truth_false']}`.",
            "",
            "## Interpretation",
            "",
            "Jev did not change the answer path or deterministic route in this run. "
            "Any answer-quality delta is therefore not causally attributable to Jev "
            "from this single shadow run; model sampling, retry timing, and worker "
            "schedule remain confounders. A paired/repeated active-gate experiment "
            "would be needed for causal attribution.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--jev", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    baseline = args.baseline.expanduser().resolve()
    jev = args.jev.expanduser().resolve()
    comparison = build_comparison(baseline, jev)
    output_dir = (args.output_dir or jev).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "jev_baseline_comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "jev_baseline_comparison.md").write_text(
        render_markdown(comparison), encoding="utf-8"
    )
    print(json.dumps({"status": "completed", "output_dir": str(output_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
