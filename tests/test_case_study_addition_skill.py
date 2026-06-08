import json
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path.home() / ".codex" / "skills" / "Scout_case-study-addition"
VALIDATOR = SKILL_ROOT / "scripts" / "validate_sidecar.py"
GENERATOR = SKILL_ROOT / "scripts" / "generate_case_study.py"


def _valid_sidecar() -> dict:
    return {
        "schema_version": "case-study-addition.v0.1",
        "case_id": "raceon_pretrip_readiness_reference",
        "case_slug": "raceon-pretrip-readiness-reference",
        "status": "draft",
        "created_at": "2026-05-31T00:00:00+08:00",
        "sources": [
            {
                "source_id": "src_001",
                "type": "url",
                "title": "RaceON pretrip readiness reference",
                "url": "https://www.raceon.com.tw/zh-TW/blogs/news/182126",
                "publisher": "RaceON",
                "published_date": None,
                "accessed_at": "2026-05-31",
                "reliability": "reported_fact",
            }
        ],
        "quotes": [
            {
                "quote_id": "q_001",
                "source_id": "src_001",
                "text": "我的體能可以應付這座山嗎？",
                "reason": "pre-trip readiness framing",
                "copyright_check": "short_excerpt",
            }
        ],
        "timeline": [
            {
                "time_ref": "pre_trip",
                "event": "pretrip_readiness_reference",
                "source_refs": ["q_001"],
                "confidence": "reported_fact",
            }
        ],
        "taxonomy_keys": ["pretrip_fitness_readiness", "pace_buffer_required"],
        "scout_implications": [
            {
                "implication_id": "imp_001",
                "phase": "phase_4_pretrip_planning",
                "hook": "pretrip_readiness.fitness_baseline",
                "type": "spec_gap",
                "summary": "Scout should compare route workload with user fitness baseline before departure.",
                "source_refs": ["q_001"],
                "confidence": "assumption",
            }
        ],
        "boundaries": {
            "medical": "not_diagnosis",
            "legal": "no_fault_assignment",
            "rescue": "not_official_sop",
            "phase_change": "requires_human_review",
        },
        "discussion_questions": [
            "Should pre-trip readiness warnings include route workload and personal pace buffer?"
        ],
        "promotion": {
            "recommended_target": "docs/case_studies/accepted/",
            "phase_1_patch_required": False,
            "phase_2_patch_required": False,
            "fixture_required": False,
        },
    }


def _write_sidecar(tmp_path: Path, payload: dict) -> Path:
    sidecar = tmp_path / "sidecar.json"
    sidecar.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return sidecar


def _run_validator(sidecar: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(sidecar)],
        check=False,
        text=True,
        capture_output=True,
    )


def test_scout_case_study_skill_files_are_installed() -> None:
    assert (SKILL_ROOT / "SKILL.md").is_file()
    assert VALIDATOR.is_file()
    assert GENERATOR.is_file()


def test_validator_accepts_valid_sidecar(tmp_path: Path) -> None:
    result = _run_validator(_write_sidecar(tmp_path, _valid_sidecar()))

    assert result.returncode == 0, result.stderr
    assert "valid" in result.stdout


def test_validator_rejects_quote_over_100_unicode_characters(tmp_path: Path) -> None:
    payload = _valid_sidecar()
    payload["quotes"][0]["text"] = "超" * 101

    result = _run_validator(_write_sidecar(tmp_path, payload))

    assert result.returncode == 1
    assert "quote exceeds 100 Unicode characters" in result.stderr


def test_validator_rejects_fixed_corridor_without_route_evidence(tmp_path: Path) -> None:
    payload = _valid_sidecar()
    payload["taxonomy_keys"] = ["historical_gpx_corridor_width"]
    payload["scout_implications"][0].update(
        {
            "hook": "route_corridor.fixed_width",
            "summary": "Scout should use a fixed 5 m corridor for this route.",
            "confidence": "assumption",
        }
    )

    result = _run_validator(_write_sidecar(tmp_path, payload))

    assert result.returncode == 1
    assert "fixed trail corridor width requires route evidence" in result.stderr


def test_validator_rejects_gps_only_precision_navigation_claim(tmp_path: Path) -> None:
    payload = _valid_sidecar()
    payload["taxonomy_keys"] = ["precision_navigation_l3"]
    payload["scout_implications"][0].update(
        {
            "hook": "precision_navigation_mode.l3_gps_only",
            "phase": "phase_1_navigation_research",
            "summary": "L3 can rely on GPS-only precision to determine route deviation.",
            "confidence": "assumption",
        }
    )

    result = _run_validator(_write_sidecar(tmp_path, payload))

    assert result.returncode == 1
    assert "precision navigation cannot claim GPS-only precision" in result.stderr


def test_generator_writes_draft_and_sidecar(tmp_path: Path) -> None:
    output_dir = tmp_path / "case_studies"
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--case-slug",
            "raceon-pretrip-readiness-reference",
            "--title",
            "RaceON pretrip readiness reference",
            "--source-url",
            "https://www.raceon.com.tw/zh-TW/blogs/news/182126",
            "--quote",
            "我的體能可以應付這座山嗎？",
            "--taxonomy",
            "pretrip_fitness_readiness",
            "--hook",
            "pretrip_readiness.fitness_baseline",
            "--summary",
            "Scout should compare route workload with user fitness baseline before departure.",
            "--discussion-question",
            "Should pre-trip readiness warnings include route workload and personal pace buffer?",
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    draft_dir = output_dir / "drafts" / "raceon-pretrip-readiness-reference"
    assert (draft_dir / "draft.md").is_file()
    assert (draft_dir / "sidecar.json").is_file()

    sidecar = json.loads((draft_dir / "sidecar.json").read_text(encoding="utf-8"))
    assert sidecar["taxonomy_keys"] == ["pretrip_fitness_readiness"]
