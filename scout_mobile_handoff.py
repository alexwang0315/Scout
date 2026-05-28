from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from scout_energy_models import ScoutEnergyBoundary, ScoutEnergyDataQuality, ScoutEnergyPrivacy, aggregate_sha256, sha256_file


DEFAULT_MOBILE_HANDOFF_FILENAME = "mobile_energy_companion_handoff.json"


def build_mobile_energy_companion_handoff(
    *,
    daily_home_preview_path: Path,
    companion_match_review_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    daily_home = json.loads(daily_home_preview_path.read_text(encoding="utf-8"))
    _assert_daily_home_boundary(daily_home)
    companion_review = (
        json.loads(companion_match_review_path.read_text(encoding="utf-8"))
        if companion_match_review_path
        else None
    )
    if companion_review is not None:
        _assert_companion_review_boundary(companion_review)

    handoff = build_mobile_energy_companion_handoff_model(
        daily_home,
        daily_home_preview_path=daily_home_preview_path,
        companion_match_review=companion_review,
        companion_match_review_path=companion_match_review_path,
    )
    resolved_output_path = output_path or daily_home_preview_path.parent / DEFAULT_MOBILE_HANDOFF_FILENAME
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact_kind": "scout_mobile_energy_companion_handoff_result",
        "persisted": True,
        "handoff_path": str(resolved_output_path),
        "source_provider": handoff["source_provider"],
        "source_path": handoff["source_path"],
        "sha256": handoff["sha256"],
        "handoff": handoff,
        "data_quality": handoff["data_quality"],
        "privacy": handoff["privacy"],
        "boundary": handoff["boundary"],
        "mutation": {
            "mobile_handoff_written": True,
            "source_file_mutated": False,
            "network_sync_performed": False,
            "remote_upload_performed": False,
            "mobile_runtime_state_mutated": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def build_mobile_energy_companion_handoff_model(
    daily_home: dict[str, Any],
    *,
    daily_home_preview_path: Path,
    companion_match_review: dict[str, Any] | None = None,
    companion_match_review_path: Path | None = None,
) -> dict[str, Any]:
    source_artifacts = [
        {
            "artifact_kind": daily_home["artifact_kind"],
            "source_path": str(daily_home_preview_path),
            "sha256": daily_home["sha256"],
        }
    ]
    if companion_match_review is not None and companion_match_review_path is not None:
        source_artifacts.append(
            {
                "artifact_kind": companion_match_review["artifact_kind"],
                "source_path": str(companion_match_review_path),
                "sha256": companion_match_review["sha256"],
            }
        )
    source_sha = aggregate_sha256(
        [
            daily_home["sha256"],
            companion_match_review["sha256"] if companion_match_review else "",
            {
                "artifact": "mobile_energy_companion_handoff",
                "network_sync_performed": False,
                "mobile_runtime_authority": False,
            },
        ]
    )
    data_quality = _combine_quality(
        daily_home.get("data_quality", {}),
        companion_match_review.get("data_quality", {}) if companion_match_review else None,
    )
    privacy = ScoutEnergyPrivacy().model_dump(mode="json")
    boundary = ScoutEnergyBoundary().model_dump(mode="json")
    return {
        "artifact_kind": "scout_mobile_energy_companion_handoff",
        "artifact_version": "mobile_energy_companion_handoff.v1",
        "source_provider": _handoff_source_provider(daily_home, companion_match_review),
        "source_path": "+".join(artifact["source_path"] for artifact in source_artifacts),
        "sha256": source_sha,
        "surface": "mobile_energy_companion_home",
        "source_artifacts": source_artifacts,
        "energy": _mobile_energy_payload(daily_home),
        "companion_match": _mobile_companion_payload(companion_match_review),
        "sync_policy": {
            "handoff_only": True,
            "network_sync_allowed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "mobile_runtime_authority": False,
            "phase1_safety_state_authority": False,
            "offline_first_consumer_contract": True,
        },
        "display_language_policy": {
            "medical_language_allowed": False,
            "diagnosis_allowed": False,
            "runtime_safety_truth": False,
            "wording": "baseline-relative advisory trend and companion rhythm similarity only",
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy,
        "boundary": boundary,
    }


def run_mobile_handoff_cli(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "build":
        return 0, build_mobile_energy_companion_handoff(
            daily_home_preview_path=args.daily_home_preview,
            companion_match_review_path=args.companion_match_review,
            output_path=args.output,
        )
    parser.error("missing command")


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, payload = run_mobile_handoff_cli(argv)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return exit_code


def _mobile_energy_payload(daily_home: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_kind": daily_home["artifact_kind"],
        "reference_date": daily_home["reference_date"],
        "hero": daily_home["hero"],
        "trend_cards": daily_home["trend_cards"],
        "trend_markers": daily_home["trend_markers"],
        "recent_load_and_recovery_explanation": daily_home["recent_load_and_recovery_explanation"],
        "next_day_soft_cue": daily_home["next_day_soft_cue"],
    }


def _mobile_companion_payload(companion_match_review: dict[str, Any] | None) -> dict[str, Any]:
    if companion_match_review is None:
        return {
            "available": False,
            "ranked_matches": [],
            "recommended_review_refs": [],
            "review_policy": {
                "mobile_display_available": False,
                "human_review_required_for_mismatch": True,
                "auto_departure_approval_allowed": False,
                "runtime_safety_truth": False,
            },
        }
    return {
        "available": True,
        "artifact_kind": companion_match_review["artifact_kind"],
        "query_profile_ref": companion_match_review["query_profile_ref"],
        "candidate_count": companion_match_review["candidate_count"],
        "ranked_matches": [
            {
                "candidate_profile_ref": match["candidate_profile_ref"],
                "match_score": match["match_score"],
                "match_band": match["match_band"],
                "explanations": match.get("explanations", [])[:4],
                "mismatch_notes": match.get("mismatch_notes", [])[:4],
            }
            for match in companion_match_review.get("ranked_matches", [])
        ],
        "recommended_review_refs": companion_match_review.get("recommended_review_refs", []),
        "review_policy": {
            "mobile_display_available": True,
            "human_review_required_for_mismatch": True,
            "auto_departure_approval_allowed": False,
            "runtime_safety_truth": False,
            "source_review_policy": {
                key: companion_match_review.get("review_policy", {}).get(key)
                for key in [
                    "score_threshold",
                    "minimum_activity_count_for_public_match",
                    "query_public_match_display_allowed",
                    "planning_use_only_after_review",
                ]
                if key in companion_match_review.get("review_policy", {})
            },
        },
    }


def _assert_daily_home_boundary(daily_home: dict[str, Any]) -> None:
    if daily_home.get("artifact_kind") != "scout_wearable_daily_home_preview":
        raise ValueError("mobile handoff requires scout_wearable_daily_home_preview")
    _assert_boundary_privacy(daily_home, label="daily home preview")


def _assert_companion_review_boundary(companion_review: dict[str, Any]) -> None:
    if companion_review.get("artifact_kind") != "scout_companion_match_review":
        raise ValueError("mobile handoff companion input requires scout_companion_match_review")
    _assert_boundary_privacy(companion_review, label="companion match review")
    policy = companion_review.get("review_policy", {})
    if policy.get("runtime_safety_truth") is not False:
        raise ValueError("mobile handoff companion review cannot be runtime safety truth")
    if policy.get("auto_departure_approval_allowed") is not False:
        raise ValueError("mobile handoff companion review cannot approve departure")


def _assert_boundary_privacy(payload: dict[str, Any], *, label: str) -> None:
    boundary = payload.get("boundary", {})
    privacy = payload.get("privacy", {})
    if boundary.get("medical_diagnosis") is not False:
        raise ValueError(f"{label} requires medical_diagnosis=false")
    if boundary.get("phase1_runtime_safety_truth") is not False:
        raise ValueError(f"{label} cannot be Phase 1 runtime safety truth")
    if boundary.get("safety_api_calls_allowed") is not False:
        raise ValueError(f"{label} cannot allow safety API calls")
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared"):
        raise ValueError(f"{label} cannot share raw health payloads or tracks")
    if privacy.get("exact_timestamps_shared") or privacy.get("home_work_trace_shared"):
        raise ValueError(f"{label} cannot share exact timestamps or home/work traces")


def _combine_quality(first: dict[str, Any], second: dict[str, Any] | None) -> ScoutEnergyDataQuality:
    qualities = [first]
    if second:
        qualities.append(second)
    order = {"low": 0, "medium": 1, "high": 2}
    return ScoutEnergyDataQuality(
        heart_rate_confidence=min((quality.get("heart_rate_confidence", "low") for quality in qualities), key=order.get),
        gps_confidence=min((quality.get("gps_confidence", "low") for quality in qualities), key=order.get),
        missing_hr_seconds=sum(quality.get("missing_hr_seconds", 0) for quality in qualities),
        sample_cadence_s=None,
        provider_value_confidence=min((quality.get("provider_value_confidence", "low") for quality in qualities), key=order.get),
        limitations=sorted(
            {
                limitation
                for quality in qualities
                for limitation in quality.get("limitations", [])
            }
            | {"mobile handoff package is local-only and performs no network sync"}
        ),
    )


def _handoff_source_provider(
    daily_home: dict[str, Any],
    companion_match_review: dict[str, Any] | None,
) -> str:
    if companion_match_review is None:
        return daily_home["source_provider"]
    return "mobile_energy_companion_handoff"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build local Scout mobile handoff artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser(
        "build",
        help="Build a local mobile energy/companion handoff artifact without network sync.",
    )
    build_parser.add_argument("--daily-home-preview", type=Path, required=True)
    build_parser.add_argument("--companion-match-review", type=Path, default=None)
    build_parser.add_argument("--output", type=Path, required=True)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
