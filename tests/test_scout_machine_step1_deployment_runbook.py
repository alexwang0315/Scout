from pathlib import Path


RUNBOOK_PATH = Path("docs/admin/scout-machine-step1-deployment-runbook.md")
INDEX_PATH = Path("docs/admin/scout-machine-step1-evidence-index.md")


def test_step1_deployment_runbook_freezes_service_and_rollback_contract() -> None:
    source = RUNBOOK_PATH.read_text(encoding="utf-8")

    for token in (
        "Service: `scout-runtime`",
        "`/home/alexwang0315/scout-fusion-runtime/docker-compose.pi.yml`",
        "image id: `761115bf441b`",
        "rollback tag: `scout-fusion/pi-runtime:rollback-20260520T031746Z`",
        "docker tag scout-fusion/pi-runtime:rollback-20260520T031746Z scout-fusion/pi-runtime:local",
        "docker compose -f docker-compose.pi.yml up -d --no-build --force-recreate scout",
    ):
        assert token in source


def test_step1_deployment_runbook_keeps_step1_boundaries() -> None:
    source = RUNBOOK_PATH.read_text(encoding="utf-8")

    for token in (
        "`SCOUT_ENABLE_LIVE_HARDWARE=0`",
        "`SCOUT_ENABLE_AI_INFERENCE=0`",
        "`SCOUT_ENABLE_LOCAL_MODEL=0`",
        "`SCOUT_EVENT_BUS=none`",
        "Do not query or control `scout-ollama`",
        "Do not enable local model fallback",
        "Do not store passwords, tokens, or API keys",
    ):
        assert token in source


def test_step1_evidence_index_names_all_validated_evidence_directories() -> None:
    source = INDEX_PATH.read_text(encoding="utf-8")

    for token in (
        "`/data/scout/deployments/20260520T031746Z`",
        "`/data/scout/deployments/fixture-observation-20260520T033354Z`",
        "`/data/scout/deployments/canonical-fixture-observation-20260520T035132Z`",
        "`observations_processed`: `0 -> 1`",
        "`observations_processed`: `1 -> 2`",
        "checkpoint: `cp_01`",
        "`canonical-fixture-observation-summary.json`",
    ):
        assert token in source


def test_step1_evidence_index_preserves_boundary_notes() -> None:
    source = INDEX_PATH.read_text(encoding="utf-8")

    for token in (
        "must not contain passwords, tokens, API keys",
        "does not prove live hardware streaming",
        "does not prove local model fallback",
        "does not prove outbound/SOS/SMS/satellite delivery",
        "does not permit assistant, runtime stream, GPIO, or provider control paths",
    ):
        assert token in source
