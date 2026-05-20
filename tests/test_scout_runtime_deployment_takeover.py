from pathlib import Path


DOC_PATH = Path("docs/admin/scout-runtime-deployment-takeover.md")


def test_scout_runtime_deployment_takeover_records_service_promotion() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "Deployment id: `20260520T031746Z`",
        "`scout-fusion/pi-runtime:rollback-20260520T031746Z`",
        "source image tag: `scout-fusion/pi-runtime:step1`",
        "deployed service tag: `scout-fusion/pi-runtime:local`",
        "deployed image id: `761115bf441b`",
        "restart policy: `unless-stopped`",
    ):
        assert token in source


def test_scout_runtime_deployment_takeover_keeps_step1_boundaries() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "`SCOUT_ENABLE_LIVE_HARDWARE=0`",
        "`SCOUT_ENABLE_AI_INFERENCE=0`",
        "`SCOUT_ENABLE_LOCAL_MODEL=0`",
        "`SCOUT_EVENT_BUS=none`",
        "no `POST /safety/observations`",
        "no local model request",
        "provider `control_allowed=false`",
    ):
        assert token in source
