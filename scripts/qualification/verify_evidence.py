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
        "merge-gate.json",
        "qualification-summary.md",
        "review-items.json",
        "reviewer-input.json",
        "reviewer-error.json",
        "reviewer-verdict.json",
        PACKET_INDEX_NAME,
    }
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entries(evidence_root: Path) -> list[dict[str, str]]:
    return [
        {"path": path.relative_to(evidence_root).as_posix(), "sha256": _sha256(path)}
        for path in sorted(evidence_root.rglob("*"))
        if path.is_file()
        and path.name != INDEX_NAME
        and path.relative_to(evidence_root).as_posix() not in POST_REVIEW_FILES
    ]


def _root_hash(entries: list[dict[str, str]]) -> str:
    canonical = "".join(
        f"{entry['sha256']}  {entry['path']}\n" for entry in entries
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_index(evidence_root: Path) -> dict[str, Any]:
    entries = _entries(evidence_root)
    return {
        "schema": "scout.dashboardQualificationEvidenceIndex.v1",
        "evidence_root_sha256": _root_hash(entries),
        "files": entries,
    }


def build_packet_index(evidence_root: Path) -> dict[str, Any]:
    entries = [
        {"path": path.relative_to(evidence_root).as_posix(), "sha256": _sha256(path)}
        for path in sorted(evidence_root.rglob("*"))
        if path.is_file() and path.name != PACKET_INDEX_NAME
    ]
    return {
        "schema": "scout.dashboardQualificationPacketIndex.v1",
        "packet_sha256": _root_hash(entries),
        "files": entries,
    }


def verify_index(evidence_root: Path, index_path: Path) -> dict[str, Any]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    expected = {entry["path"]: entry["sha256"] for entry in index.get("files", [])}
    actual_entries = _entries(evidence_root)
    actual = {entry["path"]: entry["sha256"] for entry in actual_entries}
    mismatches = sorted(
        path
        for path in set(expected) | set(actual)
        if expected.get(path) != actual.get(path)
    )
    root_matches = _root_hash(actual_entries) == index.get("evidence_root_sha256")
    return {
        "valid": not mismatches and root_matches,
        "mismatches": mismatches,
        "evidence_root_sha256": _root_hash(actual_entries),
        "indexed_file_count": len(expected),
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
