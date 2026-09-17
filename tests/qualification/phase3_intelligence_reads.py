"""Observed Intelligence read transitions on sealed local SQLite fixtures."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import ExitStack, closing
from datetime import UTC, datetime
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scout.nextgen.dashboard_telemetry import SQLiteBackgroundIntelligenceTelemetryReader
from scout.nextgen.dashboard_telemetry_api import create_intelligence_telemetry_router
from scout.nextgen.background_job_store import SQLiteBackgroundIntelligenceJobStore
from scout.nextgen.praison_background_queue import BackgroundIntelligenceJobProgress, BackgroundIntelligenceJobState
from tests.test_scout_ai_dashboard_telemetry import _persist_completed_job, _request
from tests.qualification.contracts import canonical_sha256, file_sha256
from tests.qualification.effects import EffectAudit
from tests.qualification.sqlite_fixtures import ReadOnlySqliteFixture

INTELLIGENCE_CASES = (
    "unconfigured", "missing", "ready", "unknown-schema", "malformed",
    "stale-binding", "wal-current", "restore", "api-read-only", "reason-codes",
)


def run_intelligence_reads(*, execution_root: Path, repository_root: Path):
    from tests.qualification.phase3_telemetry import READ_TELEMETRY_CONTRACTS, ReadTelemetryReplay
    contract = next(item for item in READ_TELEMETRY_CONTRACTS if item.route == "surface-intelligence")
    if contract.synthetic_loopback_primitives != ("sqlite3.connect:sealed-execution-fixture:mode=ro:query_only=on",):
        raise ValueError("Intelligence replay requires its exact declared SQLite fixture primitive")
    with ExitStack() as fixture_handles:
        results = []
        for name in INTELLIGENCE_CASES:
            root = execution_root / "surface-intelligence" / name
            root.mkdir(parents=True, exist_ok=False)
            path = root / "jobs.sqlite3"
            writer = None
            request = response = job_id = None
            if name not in {"unconfigured", "missing", "wal-current"}:
                request, response, job_id = _persist_completed_job(path)
            if name in {"unknown-schema", "malformed", "stale-binding", "restore", "reason-codes"}:
                with closing(sqlite3.connect(path)) as connection, connection:
                    original_request, original_response = connection.execute(
                        "SELECT request_json, response_json FROM background_intelligence_jobs"
                    ).fetchone()
                    if name in {"unknown-schema", "restore"}:
                        value = json.loads(original_request)
                        value["schema_version"] = "unsupported.future.v999"
                        connection.execute("UPDATE background_intelligence_jobs SET request_json = ?", (json.dumps(value),))
                    elif name == "malformed":
                        connection.execute("UPDATE background_intelligence_jobs SET response_json = ?", ('{"runtime_safety_truth":true}',))
                    elif name == "stale-binding":
                        value = json.loads(original_response)
                        value["provenance"]["workspace_binding"]["workspace_revision"] = "unreviewed-revision"
                        connection.execute("UPDATE background_intelligence_jobs SET response_json = ?", (json.dumps(value),))
                    else:
                        # Raw validation strings are never surfaced as authority.
                        value = json.loads(connection.execute("SELECT progress_json FROM background_intelligence_jobs").fetchone()[0])
                        value["validation_reasons"] = ["malformed private raw text with unknown external approval"]
                        connection.execute("UPDATE background_intelligence_jobs SET progress_json = ?", (json.dumps(value),))
            if name == "wal-current":
                request = _request()
                progress = BackgroundIntelligenceJobProgress(
                    request_id=request.request_id, mission_id=request.mission_id,
                    workspace_binding=request.workspace_binding,
                    state=BackgroundIntelligenceJobState.QUEUED, stage="queued",
                    progress_percent=0, submitted_at=datetime.now(UTC),
                )
                writer = fixture_handles.enter_context(SQLiteBackgroundIntelligenceJobStore(path))
                writer.save_job(request=request, progress=progress, response=None, event_type="queued")
                job_id = str(progress.job_id)
                assert Path(str(path) + "-wal").is_file()
            fixtures = () if not path.exists() else (ReadOnlySqliteFixture.seal(path, execution_root=root, allow_empty_wal_coordination=True),)
            before = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            reader = SQLiteBackgroundIntelligenceTelemetryReader(None if name == "unconfigured" else path)
            audit = EffectAudit(
                transition_id=f"phase3.intelligence-read.{name}",
                roots=(("execution", root), ("repository", repository_root)),
                readonly_sqlite_fixtures=fixtures,
            )
            status, detail, observation = "passed", "", None
            try:
                with audit:
                    if name == "api-read-only":
                        app = FastAPI()
                        app.include_router(create_intelligence_telemetry_router(reader=reader))
                        with TestClient(app) as client:
                            reply = client.get("/admin/intelligence/telemetry")
                            assert reply.status_code == 200
                            assert reply.headers["cache-control"] == "no-store"
                            assert client.post("/admin/intelligence/telemetry").status_code == 405
                            observation = reply.json()
                            assert observation["status"] == "ready"
                    else:
                        snapshot = reader.snapshot()
                        observation = snapshot.model_dump(mode="json")
                        expected = (
                            "unavailable" if name in {"unconfigured", "missing"}
                            else "degraded" if name in {"unknown-schema", "malformed", "stale-binding", "restore"}
                            else "ready"
                        )
                        assert snapshot.status == expected, (name, snapshot.status, snapshot.status_reason)
                        if expected == "ready":
                            assert len(snapshot.jobs) == 1
                            assert str(snapshot.jobs[0].job_id) == job_id
                            assert snapshot.jobs[0].workspace_binding == request.workspace_binding
                        else:
                            assert snapshot.jobs == ()
                    assert observation["read_only"] is True
                    assert observation["candidate_only"] is True
                    assert observation["runtime_safety_truth"] is False
                    assert observation["promotion_result"] == "not_promoted"
                    if request is not None:
                        assert request.question not in json.dumps(observation)
                    if name == "reason-codes":
                        assert "private raw text" not in json.dumps(observation)
                        assert observation["jobs"][0]["validation_reason_codes"] == ["malformed_response"]
                    if name == "missing":
                        assert not path.exists()
                if before is not None:
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
                if name == "restore":
                    # Fixture repair occurs outside the observed read transition.
                    with closing(sqlite3.connect(path)) as connection, connection:
                        connection.execute("UPDATE background_intelligence_jobs SET request_json = ?", (original_request,))
                    restored_before = hashlib.sha256(path.read_bytes()).hexdigest()
                    restored_audit = EffectAudit(
                        transition_id="phase3.intelligence-read.restore-recovery",
                        roots=(("execution", root), ("repository", repository_root)),
                        readonly_sqlite_fixtures=(ReadOnlySqliteFixture.seal(path, execution_root=root, allow_empty_wal_coordination=True),),
                    )
                    with restored_audit:
                        restored = reader.snapshot()
                        assert restored.status == "ready" and len(restored.jobs) == 1
                        assert str(restored.jobs[0].job_id) == job_id
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == restored_before
                    observation = {"before": observation, "after": restored.model_dump(mode="json")}
                    extra = restored_audit.attempts
                else:
                    extra = ()
            except (KeyboardInterrupt, GeneratorExit):
                raise
            except BaseException as error:
                status, detail, extra = "failed", f"{type(error).__name__}: {error}", ()
            finally:
                if writer is not None:
                    writer.close()
            results.append(ReadTelemetryReplay(
                route="surface-intelligence", node_id=f"production-intelligence:{name}",
                status=status, source_sha256=file_sha256(Path(__file__)),
                attempted_effects=tuple((item.operation, item.effect_class, item.scope, item.outcome) for item in (*audit.attempts, *extra)),
                detail=detail, observation_sha256=canonical_sha256(observation),
            ))
    return tuple(results)
