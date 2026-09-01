from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from scout.nextgen.background_job_store import SQLiteBackgroundIntelligenceJobStore
from scout.nextgen.dashboard_telemetry import (
    SQLiteBackgroundIntelligenceTelemetryReader,
)
from scout.nextgen.dashboard_telemetry_api import (
    create_intelligence_telemetry_router,
)
from scout.nextgen.intelligence_gateway import (
    CapabilityBroker,
    Evidence,
    Finding,
    GatewayValidationDisposition,
    IntelligenceProvenance,
    IntelligenceRequest,
    IntelligenceResponse,
    IntelligenceTaskType,
    ModelExecutionRecord,
    WorkspaceBinding,
    seal_intelligence_response,
)
from scout.nextgen.praison_background_queue import (
    BackgroundIntelligenceJobProgress,
    BackgroundIntelligenceJobState,
)


def _request() -> IntelligenceRequest:
    request_id = uuid4()
    binding = WorkspaceBinding(
        workspace_id="workspace-telemetry",
        workspace_revision="revision-7",
        mission_id="mission-telemetry",
        mission_version="mission-version-3",
        route_id="route-telemetry",
        route_version="route-version-2",
        input_hash="input-hash-telemetry",
        generated_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
    )
    grant = CapabilityBroker().issue_grant(
        request_id=request_id,
        mission_id=binding.mission_id,
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        allowed_capabilities=("route.read", "dem.read", "qgis.processing.slope"),
        evidence_refs_allowed=("route:telemetry", "dem:telemetry"),
        max_runtime_seconds=180,
        max_model_requests=10,
        max_tool_calls=10,
        provenance_ref="grant:telemetry-test",
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id=binding.mission_id,
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question="Private route question that must not appear in Dashboard telemetry.",
        workspace_binding=binding,
        capability_grant=grant,
        evidence_refs=("route:telemetry", "dem:telemetry"),
        max_runtime_seconds=180,
        max_model_requests=10,
    )


def _response(request: IntelligenceRequest) -> IntelligenceResponse:
    started_at = datetime(2026, 9, 1, 8, 1, tzinfo=UTC)
    evidence = Evidence(
        evidence_id="evidence-slope-1",
        source_type="qgis_candidate_artifact",
        source_ref="artifact:terrain/slope-1.tif",
        content_hash="evidence-content-hash",
        summary="Candidate steep terrain derived from the bounded DEM.",
        method="qgis.processing.slope",
        resolution="20m",
    )
    record = ModelExecutionRecord(
        parent_request_id=request.request_id,
        inference_id=uuid4(),
        runtime_id="edge.pi.ollama.cpu.background",
        provider="ollama",
        model_id="qwen3:1.7b",
        observed_model_id="qwen3:1.7b",
        locality="edge",
        started_at=started_at,
        completed_at=datetime(2026, 9, 1, 8, 1, 12, tzinfo=UTC),
        latency_ms=12_000,
        model_request_count=1,
        input_tokens=820,
        output_tokens=140,
        status="completed",
        selection_reason="bounded Pi background reasoning",
    )
    response = IntelligenceResponse(
        request_id=request.request_id,
        findings=(
            Finding(
                finding_id="finding-steep-1",
                claim="A candidate steep segment intersects the route corridor.",
                confidence=0.72,
                evidence_ids=(evidence.evidence_id,),
            ),
        ),
        evidence=(evidence,),
        provenance=IntelligenceProvenance(
            request_id=request.request_id,
            service_name="scout-intelligence-service",
            service_version="0.1",
            agent_path=("praisonai.orchestrator", "terrain"),
            tools_called=("route.read", "dem.read", "qgis.processing.slope"),
            model_runtimes=(record.runtime_id,),
            model_execution_records=(record,),
            capability_grant_id=request.capability_grant.grant_id,
            workspace_binding=request.workspace_binding,
            output_hash="unsealed",
        ),
    )
    return seal_intelligence_response(response)


def _persist_completed_job(
    path: Path,
) -> tuple[IntelligenceRequest, IntelligenceResponse, str]:
    request = _request()
    response = _response(request)
    completed_at = datetime(2026, 9, 1, 8, 2, tzinfo=UTC)
    progress = BackgroundIntelligenceJobProgress(
        request_id=request.request_id,
        mission_id=request.mission_id,
        workspace_binding=request.workspace_binding,
        state=BackgroundIntelligenceJobState.COMPLETED,
        stage="completed",
        progress_percent=100,
        submitted_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
        started_at=datetime(2026, 9, 1, 8, 1, tzinfo=UTC),
        completed_at=completed_at,
        response_available=True,
        validation_disposition=GatewayValidationDisposition.ACCEPTED_CANDIDATE,
    )
    with SQLiteBackgroundIntelligenceJobStore(path) as store:
        store.save_job(
            request=request,
            progress=progress,
            response=response,
            event_type="completed",
        )
    return request, response, str(progress.job_id)


def test_missing_telemetry_store_is_unavailable_and_never_created(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "missing" / "jobs.sqlite3"

    snapshot = SQLiteBackgroundIntelligenceTelemetryReader(store_path).snapshot()

    assert snapshot.status == "unavailable"
    assert snapshot.status_reason == "store_not_found"
    assert snapshot.jobs == ()
    assert snapshot.read_only is True
    assert snapshot.candidate_only is True
    assert snapshot.runtime_safety_truth is False
    assert not store_path.exists()
    assert not store_path.parent.exists()


def test_completed_job_projects_bounded_candidate_only_telemetry(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "jobs.sqlite3"
    request, response, job_id = _persist_completed_job(store_path)
    before = store_path.stat()
    with sqlite3.connect(store_path) as connection:
        before_schema = tuple(
            connection.execute(
                "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()
        )
        before_counts = (
            connection.execute(
                "SELECT COUNT(*) FROM background_intelligence_jobs"
            ).fetchone()[0],
            connection.execute(
                "SELECT COUNT(*) FROM background_intelligence_job_events"
            ).fetchone()[0],
        )

    snapshot = SQLiteBackgroundIntelligenceTelemetryReader(store_path).snapshot()

    after = store_path.stat()
    assert snapshot.status == "ready"
    assert snapshot.summary.total_jobs == 1
    assert snapshot.summary.completed_jobs == 1
    job = snapshot.jobs[0]
    assert str(job.job_id) == job_id
    assert job.request_id == request.request_id
    assert job.task_type is IntelligenceTaskType.TERRAIN_ANALYSIS
    assert job.workspace_binding == request.workspace_binding
    assert job.capability.grant_id == request.capability_grant.grant_id
    assert job.capability.allowed_capabilities == (
        "dem.read",
        "qgis.processing.slope",
        "route.read",
    )
    assert "mission.write" in job.capability.denied_capabilities
    assert job.agent_path == ("praisonai.orchestrator", "terrain")
    assert job.tools_called == (
        "route.read",
        "dem.read",
        "qgis.processing.slope",
    )
    assert job.model_execution_records[0].runtime_id == "edge.pi.ollama.cpu.background"
    assert job.model_execution_records[0].model_request_count == 1
    assert job.output_hash == response.provenance.output_hash
    assert job.evidence_source_refs == ("artifact:terrain/slope-1.tif",)
    assert job.finding_count == 1
    assert job.evidence_count == 1
    assert job.validation_result == "accepted_candidate"
    assert job.promotion_result == "not_promoted"
    assert job.candidate_only is True
    assert job.runtime_safety_truth is False
    assert tuple(event.event_type for event in job.events) == ("completed",)
    serialized = snapshot.model_dump_json()
    assert request.question not in serialized
    assert job.question_hash in serialized
    assert before.st_size == after.st_size
    assert before.st_mtime_ns == after.st_mtime_ns
    with sqlite3.connect(store_path) as connection:
        after_schema = tuple(
            connection.execute(
                "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()
        )
        after_counts = (
            connection.execute(
                "SELECT COUNT(*) FROM background_intelligence_jobs"
            ).fetchone()[0],
            connection.execute(
                "SELECT COUNT(*) FROM background_intelligence_job_events"
            ).fetchone()[0],
        )
    assert after_schema == before_schema
    assert after_counts == before_counts


def test_corrupt_job_fails_closed_without_partial_projection(tmp_path: Path) -> None:
    store_path = tmp_path / "corrupt.sqlite3"
    _persist_completed_job(store_path)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            "UPDATE background_intelligence_jobs SET response_json = ?",
            (json.dumps({"runtime_safety_truth": True}),),
        )

    snapshot = SQLiteBackgroundIntelligenceTelemetryReader(store_path).snapshot()

    assert snapshot.status == "degraded"
    assert snapshot.status_reason == "invalid_typed_store"
    assert snapshot.jobs == ()
    assert snapshot.summary.total_jobs == 0
    assert snapshot.candidate_only is True
    assert snapshot.runtime_safety_truth is False


def test_cross_bound_response_is_degraded_and_never_silently_reused(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "stale.sqlite3"
    _persist_completed_job(store_path)
    with sqlite3.connect(store_path) as connection:
        response_json = json.loads(
            connection.execute(
                "SELECT response_json FROM background_intelligence_jobs"
            ).fetchone()[0]
        )
        response_json["provenance"]["workspace_binding"]["workspace_revision"] = (
            "revision-stale"
        )
        connection.execute(
            "UPDATE background_intelligence_jobs SET response_json = ?",
            (json.dumps(response_json),),
        )

    snapshot = SQLiteBackgroundIntelligenceTelemetryReader(store_path).snapshot()

    assert snapshot.status == "degraded"
    assert snapshot.status_reason == "invalid_typed_store"
    assert snapshot.jobs == ()
    assert snapshot.promotion_result == "not_promoted"


def test_reader_observes_committed_wal_job_while_writer_is_live(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "live-writer.sqlite3"
    request = _request()
    response = _response(request)
    completed_at = datetime.now(UTC)
    progress = BackgroundIntelligenceJobProgress(
        request_id=request.request_id,
        mission_id=request.mission_id,
        workspace_binding=request.workspace_binding,
        state=BackgroundIntelligenceJobState.COMPLETED,
        stage="completed",
        progress_percent=100,
        submitted_at=completed_at,
        started_at=completed_at,
        completed_at=completed_at,
        response_available=True,
        validation_disposition=GatewayValidationDisposition.ACCEPTED_CANDIDATE,
    )

    with SQLiteBackgroundIntelligenceJobStore(store_path) as store:
        store.save_job(
            request=request,
            progress=progress,
            response=response,
            event_type="completed",
        )
        snapshot = SQLiteBackgroundIntelligenceTelemetryReader(store_path).snapshot()

    assert snapshot.status == "ready"
    assert snapshot.jobs[0].request_id == request.request_id
    assert snapshot.jobs[0].output_hash == response.provenance.output_hash


def test_validation_reasons_are_reduced_to_server_owned_codes(tmp_path: Path) -> None:
    store_path = tmp_path / "validation-reason.sqlite3"
    request = _request()
    completed_at = datetime.now(UTC)
    progress = BackgroundIntelligenceJobProgress(
        request_id=request.request_id,
        mission_id=request.mission_id,
        workspace_binding=request.workspace_binding,
        state=BackgroundIntelligenceJobState.FAILED,
        stage="failed",
        progress_percent=100,
        submitted_at=completed_at,
        started_at=completed_at,
        completed_at=completed_at,
        error_type="ContractGatewayRejected",
        validation_disposition=GatewayValidationDisposition.REJECTED,
        validation_reasons=("malformed response included private-needle",),
    )
    with SQLiteBackgroundIntelligenceJobStore(store_path) as store:
        store.save_job(
            request=request,
            progress=progress,
            response=None,
            event_type="failed",
        )

    snapshot = SQLiteBackgroundIntelligenceTelemetryReader(store_path).snapshot()

    assert snapshot.jobs[0].validation_reason_codes == ("malformed_response",)
    assert "private-needle" not in snapshot.model_dump_json()


def test_telemetry_api_is_get_only_no_store_and_serves_page(tmp_path: Path) -> None:
    store_path = tmp_path / "api.sqlite3"
    request, _, _ = _persist_completed_job(store_path)
    app = FastAPI()
    app.include_router(
        create_intelligence_telemetry_router(
            reader=SQLiteBackgroundIntelligenceTelemetryReader(store_path)
        )
    )
    client = TestClient(app)

    telemetry = client.get("/admin/intelligence/telemetry")
    page = client.get("/admin/intelligence")
    mutation = client.post("/admin/intelligence/telemetry")

    assert telemetry.status_code == 200
    assert telemetry.headers["cache-control"] == "no-store"
    assert telemetry.json()["jobs"][0]["request_id"] == str(request.request_id)
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "data-intelligence-telemetry-page" in page.text
    assert "/admin/intelligence/telemetry" in page.text
    assert mutation.status_code == 405


def test_admin_dashboard_mounts_intelligence_surface_and_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCOUT_AI_BACKGROUND_JOB_STORE_PATH", raising=False)
    from admin_api import create_admin_app

    app = create_admin_app(runtime_audit_root=tmp_path / "runtime-audit")
    with TestClient(app) as client:
        dashboard = client.get("/admin/dashboard")
        page = client.get("/admin/intelligence")
        telemetry = client.get("/admin/intelligence/telemetry")

    assert dashboard.status_code == 200
    assert 'data-route="surface-intelligence"' in dashboard.text
    assert 'surfaceSrc("/admin/intelligence")' in dashboard.text
    assert page.status_code == 200
    assert telemetry.status_code == 200
    assert telemetry.json()["status"] == "unavailable"
    assert telemetry.json()["status_reason"] == "store_not_configured"

    repo_root = Path(__file__).resolve().parents[1]
    browser_contract = json.loads(
        (repo_root / "qualification/dashboard-browser-action-contract.json").read_text()
    )
    assert any(
        route["id"] == "surface-intelligence" for route in browser_contract["routes"]
    )
    capability_manifest = (
        repo_root / "qualification/dashboard-capability-manifest.yaml"
    ).read_text()
    assert "dashboard.intelligence.read_only_job_projection" in capability_manifest
    assert "runtime_authority: false" in capability_manifest
