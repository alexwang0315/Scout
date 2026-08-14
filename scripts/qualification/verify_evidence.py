from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


INDEX_NAME = "evidence-index.json"
PACKET_INDEX_NAME = "packet-index.json"
POST_REVIEW_FILES = frozenset(
    {
        "human-decisions.json",
        "gpt-pro-review-reference.json",
        "gpt-pro-review-status.json",
        "merge-gate.json",
        "qualification-summary.md",
        "review-items.json",
        "reviewer-input.json",
        "reviewer-error.json",
        "reviewer-verdict.json",
        PACKET_INDEX_NAME,
    }
)
ROOT_CANONICALIZATION = {
    "digest_algorithm": "sha256",
    "encoding": "utf-8",
    "line_format": "{sha256}  {path}\n",
    "sort_key": "path",
    "sort_order": "lexicographic_posix_relative_path",
}
IMAGE_MEDIA_TYPES = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect_image_media_type(path: Path) -> str:
    with path.open("rb") as handle:
        header = handle.read(16)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _entry(evidence_root: Path, path: Path) -> dict[str, str]:
    item = {
        "path": path.relative_to(evidence_root).as_posix(),
        "sha256": _sha256(path),
    }
    if path.suffix.lower() in IMAGE_MEDIA_TYPES:
        item["media_type"] = _detect_image_media_type(path)
    return item


def _entries(evidence_root: Path) -> list[dict[str, str]]:
    paths = [
        path
        for path in evidence_root.rglob("*")
        if path.is_file()
        and path.name != INDEX_NAME
        and path.relative_to(evidence_root).as_posix() not in POST_REVIEW_FILES
    ]
    return [
        _entry(evidence_root, path)
        for path in sorted(
            paths,
            key=lambda candidate: candidate.relative_to(evidence_root)
            .as_posix()
            .encode("utf-8"),
        )
    ]


def _media_type_mismatches(
    entries: list[dict[str, str]],
) -> list[dict[str, str]]:
    mismatches: list[dict[str, str]] = []
    for entry in entries:
        expected = IMAGE_MEDIA_TYPES.get(Path(entry["path"]).suffix.lower())
        if expected is None or entry.get("media_type") == expected:
            continue
        mismatches.append(
            {
                "detected_media_type": entry.get(
                    "media_type", "application/octet-stream"
                ),
                "expected_media_type": expected,
                "path": entry["path"],
            }
        )
    return mismatches


def _root_hash(entries: list[dict[str, str]]) -> str:
    canonical = "".join(
        f"{entry['sha256']}  {entry['path']}\n"
        for entry in sorted(entries, key=lambda item: item["path"].encode("utf-8"))
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_index(evidence_root: Path) -> dict[str, Any]:
    entries = _entries(evidence_root)
    media_type_mismatches = _media_type_mismatches(entries)
    if media_type_mismatches:
        raise ValueError(
            "screenshot media type mismatch: "
            + ", ".join(item["path"] for item in media_type_mismatches)
        )
    return {
        "schema": "scout.dashboardQualificationEvidenceIndex.v1",
        "evidence_root_sha256": _root_hash(entries),
        "root_canonicalization": ROOT_CANONICALIZATION,
        "files": entries,
    }


def build_packet_index(evidence_root: Path) -> dict[str, Any]:
    paths = [
        path
        for path in evidence_root.rglob("*")
        if path.is_file() and path.name != PACKET_INDEX_NAME
    ]
    entries = [
        _entry(evidence_root, path)
        for path in sorted(
            paths,
            key=lambda candidate: candidate.relative_to(evidence_root)
            .as_posix()
            .encode("utf-8"),
        )
    ]
    media_type_mismatches = _media_type_mismatches(entries)
    if media_type_mismatches:
        raise ValueError(
            "screenshot media type mismatch: "
            + ", ".join(item["path"] for item in media_type_mismatches)
        )
    return {
        "schema": "scout.dashboardQualificationPacketIndex.v1",
        "packet_sha256": _root_hash(entries),
        "root_canonicalization": ROOT_CANONICALIZATION,
        "files": entries,
    }


def verify_index(evidence_root: Path, index_path: Path) -> dict[str, Any]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    indexed_entries = {
        entry["path"]: entry for entry in index.get("files", [])
    }
    expected = {
        path: entry["sha256"] for path, entry in indexed_entries.items()
    }
    actual_entries = _entries(evidence_root)
    actual = {entry["path"]: entry["sha256"] for entry in actual_entries}
    media_type_mismatches = _media_type_mismatches(actual_entries)
    declared_media_type_mismatches = []
    for entry in actual_entries:
        actual_media_type = entry.get("media_type")
        if actual_media_type is None:
            continue
        declared_media_type = indexed_entries.get(entry["path"], {}).get(
            "media_type"
        )
        if declared_media_type is None and index.get("root_canonicalization") is None:
            continue
        if declared_media_type == actual_media_type:
            continue
        declared_media_type_mismatches.append(
            {
                "actual_media_type": actual_media_type,
                "declared_media_type": declared_media_type,
                "path": entry["path"],
            }
        )
    mismatches = sorted(
        path
        for path in set(expected) | set(actual)
        if expected.get(path) != actual.get(path)
    )
    root_matches = _root_hash(actual_entries) == index.get("evidence_root_sha256")
    declared_canonicalization = index.get("root_canonicalization")
    canonicalization_matches = declared_canonicalization in (
        None,
        ROOT_CANONICALIZATION,
    )
    return {
        "valid": (
            not mismatches
            and root_matches
            and not media_type_mismatches
            and not declared_media_type_mismatches
            and canonicalization_matches
        ),
        "mismatches": mismatches,
        "media_type_mismatches": media_type_mismatches,
        "declared_media_type_mismatches": declared_media_type_mismatches,
        "evidence_root_sha256": _root_hash(actual_entries),
        "indexed_file_count": len(expected),
        "root_canonicalization": ROOT_CANONICALIZATION,
        "root_canonicalization_valid": canonicalization_matches,
        "legacy_implicit_canonicalization": declared_canonicalization is None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify a qualification evidence index.")
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--build-packet", action="store_true")
    args = parser.parse_args()
    index_path = args.evidence_root / INDEX_NAME
    if args.build_packet:
        index = build_packet_index(args.evidence_root)
        (args.evidence_root / PACKET_INDEX_NAME).write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(index["packet_sha256"])
        return 0
    if args.build:
        index = build_index(args.evidence_root)
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(index["evidence_root_sha256"])
        return 0
    result = verify_index(args.evidence_root, index_path)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
