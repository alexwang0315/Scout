from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_FIXTURE_ROOT = Path("tests/fixtures/pretrip")
DEFAULT_MAX_FILE_BYTES = 256 * 1024

RAW_BINARY_SUFFIXES = frozenset(
    {
        ".asc",
        ".bin",
        ".dem",
        ".dtm",
        ".fit",
        ".gpx",
        ".heic",
        ".jpeg",
        ".jpg",
        ".kml",
        ".kmz",
        ".las",
        ".laz",
        ".png",
        ".tif",
        ".tiff",
        ".tcx",
    }
)
RAW_ROUTE_SUFFIXES = frozenset({".fit", ".gpx", ".kml", ".kmz", ".tcx"})
JSON_SUFFIXES = frozenset({".geojson", ".json", ".jsonl"})
IGNORED_METADATA_FILENAMES = frozenset({".DS_Store"})
ALLOWED_MAP_PAYLOAD_REFS = frozenset(
    {
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/normalized/map/map_context.geojson",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/candidates/map_candidates.json",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/candidates/overpass_evidence.json",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/normalized/map/overpass_vector_evidence.geojson",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/reference_track_display_geometry.json",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/risk_ribbon.geojson",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/segment_display_geometry.json",
    }
)
ALLOWED_LARGE_METADATA_REFS = frozenset(
    {
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/candidates/overpass_evidence.json",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/normalized/map/overpass_phase_a_raw.json",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/normalized/map/overpass_vector_evidence.geojson",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/normalized/terrain/segment_dtm_coverage.json",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/pretrip_package.json",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/reference_track_display_geometry.json",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/risk_ribbon.geojson",
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/segment_display_geometry.json",
    }
)
FORBIDDEN_PATH_FRAGMENTS = ("PdrSample", "raw_samples")
FORBIDDEN_JSON_KEYS = frozenset({"PdrSample", "raw_samples", "trkpt"})
MAP_PAYLOAD_KEYS = frozenset({"coordinates", "features"})
WORKSPACE_ONLY_OUTPUT_REFS = frozenset(
    {
        "outputs/expert_contribution_apply_plan.json",
        "outputs/expert_contribution_workspace_apply_result.json",
        "outputs/route_note_reviewed_assumptions.json",
    }
)


@dataclass(frozen=True)
class PreTripFixtureHygieneManifest:
    manifest_id: str
    phase: str
    schema_version: str
    fixture_root: str
    policy: dict[str, Any]
    counts: dict[str, int]
    issues: dict[str, list[dict[str, Any]]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "phase": self.phase,
            "schema_version": self.schema_version,
            "fixture_root": self.fixture_root,
            "policy": self.policy,
            "counts": self.counts,
            "issues": self.issues,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def build_pretrip_fixture_hygiene_manifest(
    repo_root: Path | str = Path("."),
    *,
    fixture_root_ref: str = DEFAULT_FIXTURE_ROOT.as_posix(),
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> PreTripFixtureHygieneManifest:
    root = Path(repo_root)
    fixture_root = root / fixture_root_ref
    files = sorted(
        path
        for path in fixture_root.rglob("*")
        if path.is_file() and path.name not in IGNORED_METADATA_FILENAMES
    )

    issues: dict[str, list[dict[str, Any]]] = {
        "raw_suffix_files": [],
        "oversized_files": [],
        "json_parse_errors": [],
        "forbidden_fragments": [],
    }
    json_file_count = 0

    for path in files:
        rel_ref = _relative_ref(path, root)
        suffix = path.suffix.lower()
        size_bytes = path.stat().st_size

        if suffix in RAW_BINARY_SUFFIXES:
            issues["raw_suffix_files"].append(
                {
                    "path": rel_ref,
                    "suffix": suffix,
                    "raw_route_suffix": suffix in RAW_ROUTE_SUFFIXES,
                    "size_bytes": size_bytes,
                }
            )

        if size_bytes > max_file_bytes and rel_ref not in ALLOWED_LARGE_METADATA_REFS:
            issues["oversized_files"].append(
                {
                    "path": rel_ref,
                    "size_bytes": size_bytes,
                    "max_file_bytes": max_file_bytes,
                }
            )

        for fragment in FORBIDDEN_PATH_FRAGMENTS:
            if fragment in rel_ref:
                issues["forbidden_fragments"].append(
                    {
                        "path": rel_ref,
                        "fragment": fragment,
                        "location": "path",
                    }
                )

        if suffix not in JSON_SUFFIXES:
            continue

        json_file_count += 1
        try:
            payloads = _load_json_payloads(path)
        except json.JSONDecodeError as exc:
            issues["json_parse_errors"].append(
                {
                    "path": rel_ref,
                    "line": exc.lineno,
                    "column": exc.colno,
                    "message": exc.msg,
                }
            )
            continue

        for payload in payloads:
            issues["forbidden_fragments"].extend(
                _forbidden_json_fragment_issues(payload, rel_ref)
            )

    counts = {
        "files_scanned": len(files),
        "json_files_scanned": json_file_count,
        "raw_suffix_files": len(issues["raw_suffix_files"]),
        "raw_route_suffix_files": sum(
            1 for issue in issues["raw_suffix_files"] if issue["raw_route_suffix"]
        ),
        "oversized_files": len(issues["oversized_files"]),
        "json_parse_errors": len(issues["json_parse_errors"]),
        "forbidden_fragments": len(issues["forbidden_fragments"]),
        "total_issues": sum(len(values) for values in issues.values()),
    }

    return PreTripFixtureHygieneManifest(
        manifest_id="pretrip.fixture_hygiene.v0",
        phase="phase_4_pretrip_fixture_hygiene",
        schema_version="0.1.0",
        fixture_root=fixture_root_ref,
        policy={
            "fixture_only": True,
            "no_ui_or_runtime": True,
            "raw_payload_policy": "refs_and_counts_only",
            "raw_dtm_gpx_jpg_repo_fixture_policy": "forbidden",
            "max_file_bytes": max_file_bytes,
            "raw_binary_suffixes": sorted(RAW_BINARY_SUFFIXES),
            "raw_route_suffixes": sorted(RAW_ROUTE_SUFFIXES),
            "allowed_map_payload_refs": sorted(ALLOWED_MAP_PAYLOAD_REFS),
            "allowed_large_metadata_refs": sorted(ALLOWED_LARGE_METADATA_REFS),
            "ignored_metadata_filenames": sorted(IGNORED_METADATA_FILENAMES),
        },
        counts=counts,
        issues=issues,
    )


def find_repo_fixture_workspace_output_artifacts(
    repo_root: Path | str = Path("."),
    *,
    fixture_root_ref: str = DEFAULT_FIXTURE_ROOT.as_posix(),
) -> list[str]:
    root = Path(repo_root)
    fixture_root = root / fixture_root_ref
    forbidden_refs = sorted(WORKSPACE_ONLY_OUTPUT_REFS)
    matches: list[str] = []
    for path in sorted(fixture_root.rglob("*")):
        if not path.is_file():
            continue
        rel_ref = _relative_ref(path, fixture_root)
        if rel_ref in forbidden_refs or any(
            rel_ref.endswith(f"/{forbidden_ref}") for forbidden_ref in forbidden_refs
        ):
            matches.append(_relative_ref(path, root))
    return matches


def _load_json_payloads(path: Path) -> list[Any]:
    if path.suffix.lower() != ".jsonl":
        return [json.loads(path.read_text(encoding="utf-8"))]
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _forbidden_json_fragment_issues(payload: Any, rel_ref: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for key_path, key in _walk_json_keys(payload):
        if key in FORBIDDEN_JSON_KEYS:
            issues.append(
                {
                    "path": rel_ref,
                    "fragment": key,
                    "location": "json_key",
                    "json_path": key_path,
                }
            )
            continue

        if key in MAP_PAYLOAD_KEYS and rel_ref not in ALLOWED_MAP_PAYLOAD_REFS:
            issues.append(
                {
                    "path": rel_ref,
                    "fragment": key,
                    "location": "json_key",
                    "json_path": key_path,
                }
            )
    return issues


def _walk_json_keys(payload: Any, prefix: str = "$") -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            key_path = f"{prefix}.{key_text}"
            keys.append((key_path, key_text))
            keys.extend(_walk_json_keys(value, key_path))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            keys.extend(_walk_json_keys(item, f"{prefix}[{index}]"))
    return keys


def _relative_ref(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
