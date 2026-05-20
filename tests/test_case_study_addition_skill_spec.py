from pathlib import Path


SPEC_PATH = Path("docs/specs/case-study-addition-skill.md")


def test_case_study_skill_spec_is_repo_owned_not_local_scratch() -> None:
    source = SPEC_PATH.read_text(encoding="utf-8")

    for token in (
        "# Spec: Case Study Addition Skill",
        "Repository target for this specification: `docs/specs/case-study-addition-skill.md`",
        "~/.codex/skills/Scout_case-study-addition/",
        "docs/case_studies/",
        "sidecar.json",
        "requires_human_review",
        "not_diagnosis",
        "must never apply changes automatically",
    ):
        assert token in source


def test_case_study_skill_spec_stays_outside_active_runtime_tracks() -> None:
    source = SPEC_PATH.read_text(encoding="utf-8")

    for token in (
        "without crossing into the active Phase 1 or Phase 2 implementation lines",
        "Case-study corpus work",
        "must remain separate from `docs/specs/phase-1-trail-black-box.md`",
        "until a human explicitly approves a spec patch",
        "Never: edit Phase 1 or Phase 2 runtime code as part of case-study addition",
        "Never: use case-study material to silently change Scout safety thresholds",
    ):
        assert token in source
