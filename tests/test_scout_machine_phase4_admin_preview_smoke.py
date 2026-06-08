from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-machine-phase4-admin-preview-smoke.md")
INDEX_PATH = Path("docs/admin/scout-machine-step1-evidence-index.md")


def test_phase4_admin_preview_smoke_records_target_service_and_ports() -> None:
    source = REPORT_PATH.read_text(encoding="utf-8")

    for token in (
        "Phase 4 admin preview package: `ed1688cf`",
        "`/home/alexwang0315/scout-fusion-phase4-admin-auth`",
        "`scout-pi-runtime`: healthy, host `9099 -> 9099`",
        "`scout-pi-phase4-admin`: healthy, host `9110 -> 9099`",
        "`scout-ollama`: present on `11434`, not touched by this smoke",
        "recommended_mac_url=http://scout.local:9110/admin/pretrip",
        "shares_runtime_port=false",
        "`auth.required=true`",
        "`auth.token_source=file`",
        "`auth.token_value_exposed=false`",
    ):
        assert token in source


def test_phase4_admin_preview_smoke_records_read_only_admin_and_assistant_probes() -> None:
    source = REPORT_PATH.read_text(encoding="utf-8")

    for token in (
        "`GET http://127.0.0.1:9110/admin/pretrip`",
        "HTTP `200` when authenticated",
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


def test_phase4_admin_preview_smoke_records_runtime_stream_status_route_enabled_on_hardware() -> None:
    source = REPORT_PATH.read_text(encoding="utf-8")

    for token in (
        "`GET http://scout.local:9099/runtime/streams/status-read-only` returned HTTP",
        "`200` after the field runtime was rebuilt",
        "`SCOUT_RUNTIME_STREAM_STATUS_ENABLED=true`",
        "`artifact_kind=runtime_stream_status_surface`",
        "`status=read_only_status_ready`",
        "`transport_routes_mounted=false`",
        "`observation_ingest_allowed=false`",
        "`stream_control_mutation_allowed=false`",
        "`live_provider_send_allowed=false`",
        "`safety_mutation_allowed=false`",
        "`phase2_writeback_allowed=false`",
        "runtime-stream-status-deployment-summary.json",
        "沒有開啟 observation ingest",
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
        "Admin auth was required for protected `9110` routes.",
        "Token material stayed in",
        "No Scout safety, Brain, review, outbound, local model, or hardware-provider state was changed",
    ):
        assert token in source


def test_phase4_admin_preview_smoke_records_auth_smoke_without_token_leak() -> None:
    source = REPORT_PATH.read_text(encoding="utf-8")

    for token in (
        "## Auth Smoke",
        "`phase4_hardware_demo_smoke.py --admin-token-file <temporary-token-file>`",
        "`admin_auth_header_sent=true`",
        "`admin_auth_scheme=basic`",
        "`token_value_exposed=false`",
        "`runtime_auth_header_sent=false`",
        "`GET http://scout.local:9110/admin/pretrip` without auth: HTTP `401`",
        "`GET http://scout.local:9099/health`: HTTP `200`, without an auth header.",
        "The temporary Mac token file was removed after the smoke.",
    ):
        assert token in source
    assert "secret-token" not in source


def test_phase4_admin_preview_smoke_records_tile_and_review_preview_probes() -> None:
    source = REPORT_PATH.read_text(encoding="utf-8")

    for token in (
        "## Map Tile And Review Preview Smoke",
        "`GET http://scout.local:9110/admin/tiles/osm/5/26/13.png`: HTTP `200`",
        "`content_type=image/svg+xml`, fallback tile response",
        "`GET http://scout.local:9110/admin/tiles/imagery/chilai_nanhua_day1/imagery/5/26/13.png`",
        "`content_type=image/svg+xml`, fallback imagery response",
        "`candidate_ref=contour.g11.seg_001_003`",
        "`persist_to_workspace=false`: HTTP `200`",
        "`artifact_kind=pretrip_review_decision_preview`, `preview=true`",
        "`admin_api_write_performed=false`",
        "`fixture_file_mutation_allowed=false`",
        "`phase1_runtime_mutation_allowed=false`",
        "`phase2_writeback_allowed=false`",
        "`runtime_mutation_allowed=false`",
        "review-decision smoke 只跑 preview",
    ):
        assert token in source


def test_phase4_admin_preview_smoke_records_workspace_creation_live_probe() -> None:
    source = REPORT_PATH.read_text(encoding="utf-8")

    for token in (
        "`POST http://scout.local:9110/admin/pretrip/projects/chilai_nanhua_day1/workspace`",
        "returned HTTP `200`",
        "`artifact_kind=pretrip_workspace_copy`",
        "`persisted=true`",
        "`workspace_root=/data/scout/admin/pretrip-workspaces/chilai_nanhua_day1`",
        "workspace file count: `44`",
        "workspace size: about `904KB`",
        "`project.json` present in the workspace",
        "`admin_api_write_performed=true`",
        "`workspace_file_mutation_allowed=true`",
        "`fixture_file_mutation_allowed=false`",
        "`phase1_runtime_mutation_allowed=false`",
        "`phase2_writeback_allowed=false`",
        "`runtime_mutation_allowed=false`",
        "repeat `POST /admin/pretrip/projects/chilai_nanhua_day1/workspace` returned",
        "HTTP `409`",
        "intentionally non-idempotent",
        "不寫 repo",
    ):
        assert token in source


def test_step1_evidence_index_links_phase4_admin_preview_smoke() -> None:
    source = INDEX_PATH.read_text(encoding="utf-8")

    for token in (
        "### Phase 4 Admin Preview Smoke",
        "`/home/alexwang0315/scout-fusion-phase4-admin-auth`",
        "`scout-pi-phase4-admin`: healthy",
        "admin preview port: `9110 -> 9099`",
        "admin auth: `required=true`, `token_source=file`",
        "unauthenticated `GET /admin/pretrip`: HTTP `401`",
        "`GET /admin/pretrip`: HTTP `200` when authenticated, `id=\"map\"` present",
        "`GET /assistant/status`: `provider=mock`, `token_values_exposed=false`",
        "`POST /assistant/query`: `read_only=true`, `model_interpretation=true`",
        "`GET /runtime/streams/status-read-only` on field runtime: HTTP `200`",
        "`SCOUT_RUNTIME_STREAM_STATUS_ENABLED=true`",
        "no transport route",
        "observation ingest",
        "no provider send",
        "`GET /admin/tiles/osm/5/26/13.png`: HTTP `200`, fallback tile response",
        "`GET /admin/tiles/imagery/chilai_nanhua_day1/imagery/5/26/13.png`: HTTP",
        "`persist_to_workspace=false`: HTTP `200`, preview-only, no workspace write",
        "`POST /admin/pretrip/projects/chilai_nanhua_day1/workspace`: HTTP `200`",
        "`44` files",
        "repeat workspace creation POST returned HTTP `409`",
        "docs/admin/scout-machine-phase4-admin-preview-smoke.md",
        "`scout-pi-phase4-admin` status: healthy on `9110`",
    ):
        assert token in source
