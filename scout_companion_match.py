from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from scout_companion_match_models import (
    CompanionCapabilityCapsule,
    CompanionCommunityPublishDryRun,
    CompanionPoolExchangePackage,
    CompanionConsentPoolArtifact,
    build_companion_community_publish_dry_run,
    build_companion_consent_pool,
    build_companion_match_review_from_pool,
    build_companion_match_review_artifact,
    build_companion_pool_entry,
    build_companion_pool_exchange_package,
    import_companion_pool_exchange_package,
    write_companion_community_publish_dry_run,
    write_companion_consent_pool_artifact,
    write_companion_match_review_artifact,
    write_companion_pool_exchange_package,
)


def run_companion_match_cli(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "score":
        query = _load_capsule(args.query_capsule)
        candidates = [_load_capsule(path) for path in args.candidate_capsule]
        candidate_refs = args.candidate_profile_ref
        if candidate_refs is not None and len(candidate_refs) != len(candidates):
            parser.error("--candidate-profile-ref count must match --candidate-capsule count")
        artifact = build_companion_match_review_artifact(
            query,
            candidates,
            query_profile_ref=args.query_profile_ref,
            candidate_profile_refs=candidate_refs,
            review_score_threshold=args.review_score_threshold,
        )
        write_companion_match_review_artifact(artifact, args.output)
        return 0, {
            "artifact_kind": "scout_companion_match_cli_result",
            "source_provider": artifact.source_provider,
            "source_path": artifact.source_path,
            "sha256": artifact.sha256,
            "output_path": str(args.output),
            "review": artifact.model_dump(mode="json"),
            "data_quality": artifact.data_quality.model_dump(mode="json"),
            "privacy": artifact.privacy.model_dump(mode="json"),
            "boundary": artifact.boundary.model_dump(mode="json"),
        }
    if args.command == "pool-build":
        capsules = [_load_capsule(path) for path in args.capsule]
        if len(args.public_profile_ref) != len(capsules):
            parser.error("--public-profile-ref count must match --capsule count")
        entries = [
            build_companion_pool_entry(
                capsule,
                public_profile_ref=profile_ref,
                explicit_consent=args.explicit_consent,
            )
            for capsule, profile_ref in zip(capsules, args.public_profile_ref)
        ]
        pool = build_companion_consent_pool(entries, source_path=str(args.output))
        write_companion_consent_pool_artifact(pool, args.output)
        return 0, {
            "artifact_kind": "scout_companion_pool_cli_result",
            "source_provider": pool.source_provider,
            "source_path": pool.source_path,
            "sha256": pool.sha256,
            "output_path": str(args.output),
            "pool": pool.model_dump(mode="json"),
            "data_quality": pool.data_quality.model_dump(mode="json"),
            "privacy": pool.privacy.model_dump(mode="json"),
            "boundary": pool.boundary.model_dump(mode="json"),
        }
    if args.command == "pool-score":
        query = _load_capsule(args.query_capsule)
        pool = _load_pool(args.pool)
        artifact = build_companion_match_review_from_pool(
            query,
            pool,
            query_profile_ref=args.query_profile_ref,
            include_review_only=args.include_review_only,
            review_score_threshold=args.review_score_threshold,
        )
        write_companion_match_review_artifact(artifact, args.output)
        return 0, {
            "artifact_kind": "scout_companion_pool_score_cli_result",
            "source_provider": artifact.source_provider,
            "source_path": artifact.source_path,
            "sha256": artifact.sha256,
            "output_path": str(args.output),
            "review": artifact.model_dump(mode="json"),
            "data_quality": artifact.data_quality.model_dump(mode="json"),
            "privacy": artifact.privacy.model_dump(mode="json"),
            "boundary": artifact.boundary.model_dump(mode="json"),
        }
    if args.command == "pool-export-package":
        pool = _load_pool(args.pool)
        package = build_companion_pool_exchange_package(
            pool,
            public_profile_refs=args.public_profile_ref,
            source_path=str(args.output),
        )
        write_companion_pool_exchange_package(package, args.output)
        return 0, {
            "artifact_kind": "scout_companion_pool_export_package_cli_result",
            "source_provider": package.source_provider,
            "source_path": package.source_path,
            "sha256": package.sha256,
            "output_path": str(args.output),
            "package": package.model_dump(mode="json"),
            "data_quality": package.data_quality.model_dump(mode="json"),
            "privacy": package.privacy.model_dump(mode="json"),
            "boundary": package.boundary.model_dump(mode="json"),
        }
    if args.command == "pool-import-package":
        package = _load_exchange_package(args.package)
        existing_pool = _load_pool(args.existing_pool) if args.existing_pool else None
        pool = import_companion_pool_exchange_package(
            package,
            existing_pool=existing_pool,
            source_path=str(args.output),
        )
        write_companion_consent_pool_artifact(pool, args.output)
        return 0, {
            "artifact_kind": "scout_companion_pool_import_package_cli_result",
            "source_provider": pool.source_provider,
            "source_path": pool.source_path,
            "sha256": pool.sha256,
            "output_path": str(args.output),
            "pool": pool.model_dump(mode="json"),
            "data_quality": pool.data_quality.model_dump(mode="json"),
            "privacy": pool.privacy.model_dump(mode="json"),
            "boundary": pool.boundary.model_dump(mode="json"),
        }
    if args.command == "community-publish-dry-run":
        pool = _load_pool(args.pool)
        package = build_companion_community_publish_dry_run(
            pool,
            public_profile_refs=args.public_profile_ref,
            community_ref=args.community_ref,
            explicit_community_consent=args.explicit_community_consent,
            source_path=str(args.output),
        )
        write_companion_community_publish_dry_run(package, args.output)
        return 0, {
            "artifact_kind": "scout_companion_community_publish_dry_run_cli_result",
            "source_provider": package.source_provider,
            "source_path": package.source_path,
            "sha256": package.sha256,
            "output_path": str(args.output),
            "package": package.model_dump(mode="json"),
            "data_quality": package.data_quality.model_dump(mode="json"),
            "privacy": package.privacy.model_dump(mode="json"),
            "boundary": package.boundary.model_dump(mode="json"),
        }
    parser.error("missing command")


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, payload = run_companion_match_cli(argv)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return exit_code


def _load_capsule(path: Path) -> CompanionCapabilityCapsule:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CompanionCapabilityCapsule.model_validate(payload)


def _load_pool(path: Path) -> CompanionConsentPoolArtifact:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CompanionConsentPoolArtifact.model_validate(payload)


def _load_exchange_package(path: Path) -> CompanionPoolExchangePackage:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CompanionPoolExchangePackage.model_validate(payload)


def _load_community_publish_dry_run(path: Path) -> CompanionCommunityPublishDryRun:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CompanionCommunityPublishDryRun.model_validate(payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score privacy-preserving Scout companion capability capsules.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    score_parser = subparsers.add_parser(
        "score",
        help="Build a ranked companion match review artifact from local capsules.",
    )
    score_parser.add_argument("--query-capsule", type=Path, required=True)
    score_parser.add_argument(
        "--candidate-capsule",
        action="append",
        type=Path,
        required=True,
        help="Candidate companion capability capsule JSON. Repeat for multiple candidates.",
    )
    score_parser.add_argument("--output", type=Path, required=True)
    score_parser.add_argument("--query-profile-ref", default="local_user.private")
    score_parser.add_argument("--candidate-profile-ref", action="append", default=None)
    score_parser.add_argument("--review-score-threshold", type=int, default=75)
    pool_parser = subparsers.add_parser(
        "pool-build",
        help="Build a local explicit-consent companion pool from privacy-preserving capsules.",
    )
    pool_parser.add_argument(
        "--capsule",
        action="append",
        type=Path,
        required=True,
        help="Companion capability capsule JSON. Repeat for multiple entries.",
    )
    pool_parser.add_argument(
        "--public-profile-ref",
        action="append",
        required=True,
        help="Public profile ref for the corresponding capsule. Repeat to match --capsule.",
    )
    pool_parser.add_argument("--output", type=Path, required=True)
    pool_parser.add_argument("--explicit-consent", action="store_true")
    pool_score_parser = subparsers.add_parser(
        "pool-score",
        help="Score a query capsule against a local explicit-consent companion pool.",
    )
    pool_score_parser.add_argument("--query-capsule", type=Path, required=True)
    pool_score_parser.add_argument("--pool", type=Path, required=True)
    pool_score_parser.add_argument("--output", type=Path, required=True)
    pool_score_parser.add_argument("--query-profile-ref", default="local_user.private")
    pool_score_parser.add_argument("--review-score-threshold", type=int, default=75)
    pool_score_parser.add_argument("--include-review-only", action="store_true")
    package_export_parser = subparsers.add_parser(
        "pool-export-package",
        help="Write a manual local exchange package from a consented companion pool.",
    )
    package_export_parser.add_argument("--pool", type=Path, required=True)
    package_export_parser.add_argument("--output", type=Path, required=True)
    package_export_parser.add_argument(
        "--public-profile-ref",
        action="append",
        default=None,
        help="Optional pool entry ref to include. Repeat for multiple entries.",
    )
    package_import_parser = subparsers.add_parser(
        "pool-import-package",
        help="Import a manual local exchange package into a local companion pool.",
    )
    package_import_parser.add_argument("--package", type=Path, required=True)
    package_import_parser.add_argument("--output", type=Path, required=True)
    package_import_parser.add_argument("--existing-pool", type=Path, default=None)
    community_publish_parser = subparsers.add_parser(
        "community-publish-dry-run",
        help="Build an upload-free community companion pool publish dry-run artifact.",
    )
    community_publish_parser.add_argument("--pool", type=Path, required=True)
    community_publish_parser.add_argument("--output", type=Path, required=True)
    community_publish_parser.add_argument("--community-ref", required=True)
    community_publish_parser.add_argument("--explicit-community-consent", action="store_true")
    community_publish_parser.add_argument(
        "--public-profile-ref",
        action="append",
        default=None,
        help="Optional pool entry ref to include. Repeat for multiple entries.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
