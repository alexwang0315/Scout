from pathlib import Path


RESULTS_PATH = Path("docs/admin/scout-machine-remote-smoke-results.md")


def test_scout_machine_remote_smoke_records_build_and_read_only_probes() -> None:
    source = RESULTS_PATH.read_text(encoding="utf-8")

    for token in (
        "Commit package: `b41f50cd`",
        "docker compose -f docker-compose.pi.yml build scout",
        "image: `scout-fusion/pi-runtime:step1`",
        "`GET /health`",
        "`GET /runtime/status`",
        "`GET /providers/status`",
        "`127.0.0.1:9101`",
        "The temporary container was removed after the smoke.",
    ):
        assert token in source


def test_scout_machine_remote_smoke_keeps_mutation_and_model_boundaries() -> None:
    source = RESULTS_PATH.read_text(encoding="utf-8")

    for token in (
        "不呼叫 live `/safety/*` mutation",
        "不啟動本地模型",
        "`SCOUT_ENABLE_LOCAL_MODEL=0`",
        "`POST /safety/observations` was intentionally not run",
        "This smoke did not start it, stop it, or query it.",
    ):
        assert token in source
