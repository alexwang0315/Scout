from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-machine-phase4-admin-preview-smoke.md")
INDEX_PATH = Path("docs/admin/scout-machine-step1-evidence-index.md")


def test_phase4_admin_preview_smoke_records_target_service_and_ports() -> None:
    source = REPORT_PATH.read_text(encoding="utf-8")

    for token in (
        "Phase 4 admin preview package: `e646f700`",
        "`/home/alexwang0315/scout-fusion-phase4-admin-e646f700`",
        "`scout-runtime`: healthy, host `9099 -> 9099`",
        "`scout-pi-phase4-admin`: healthy, host `9110 -> 9099`",
        "`scout-ollama`: present on `11434`, not touched by this smoke",
        "recommended_mac_url=http://scout.local:9110/admin/pretrip",
        "shares_runtime_port=false",
    ):
        assert token in source


def test_phase4_admin_preview_smoke_records_read_only_admin_and_assistant_probes() -> None:
    source = REPORT_PATH.read_text(encoding="utf-8")

    for token in (
        "`GET http://127.0.0.1:9110/admin/pretrip`",
        "HTTP `200`",
        "response size `95198` bytes",
        "`id=\"map\"` present",
        "`GET http://127.0.0.1:9110/assistant/status`",
        "`provider=mock`",
        "`token_values_exposed=false`",
        "`POST http://127.0.0.1:9110/assistant/query`",
        "`read_only=true`",
        "`model_interpretation=true`",
        "Mock provider only; no network or live Pydantic AI call was made.",
    ):
        assert token in source


def test_phase4_admin_preview_smoke_preserves_safety_and_hardware_boundaries() -> None:
    source = REPORT_PATH.read_text(encoding="utf-8")

    for token in (
        "No live `/safety/*` mutation was called.",
        "No outbound, SOS, SMS, satellite, webhook, or provider send was performed.",
        "No hardware provider was controlled.",
        "No local model request was made.",
        "No Phase 1 safety decision was changed.",
        "No Phase 2 Brain, ObservedFact, IncidentStore, or HumanReview write was made.",
        "No Scout safety, Brain, review, outbound, local model, or hardware-provider state was changed",
    ):
        assert token in source


def test_step1_evidence_index_links_phase4_admin_preview_smoke() -> None:
    source = INDEX_PATH.read_text(encoding="utf-8")

    for token in (
        "### Phase 4 Admin Preview Smoke",
        "`/home/alexwang0315/scout-fusion-phase4-admin-e646f700`",
        "`scout-pi-phase4-admin`: healthy",
        "admin preview port: `9110 -> 9099`",
        "`GET /admin/pretrip`: HTTP `200`, `id=\"map\"` present",
        "`GET /assistant/status`: `provider=mock`, `token_values_exposed=false`",
        "`POST /assistant/query`: `read_only=true`, `model_interpretation=true`",
        "docs/admin/scout-machine-phase4-admin-preview-smoke.md",
        "`scout-pi-phase4-admin` status: healthy on `9110`",
    ):
        assert token in source
