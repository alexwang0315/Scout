from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from admin_api import create_admin_router
from assistant_api import create_assistant_router
from assistant_context import create_assistant_context_resolver
from debug_api import create_debug_page_router, create_debug_router
from debug_event_provenance import DebugEventIngestionChannel
from hardware_readiness_api import create_hardware_readiness_router
from mock_outbound_transport import MockOutboundTransport
from runtime_debug_log import MemoryRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent


def create_smoke_app() -> FastAPI:
    app = FastAPI(title="Scout Admin UI Smoke App")
    app.include_router(create_admin_router())

    debug_log = MemoryRuntimeDebugEventLog(_debug_events())
    transport = MockOutboundTransport(
        session_id="debug_session.admin_ui_smoke",
        mission_id="mission.admin_ui_smoke",
        debug_log=debug_log,
        timestamp_factory=lambda: "2026-05-21T08:00:05Z",
    )
    transport.queue_message(
        category="incident_alert",
        recipient_ref="remote_contact.primary",
        subject_ref="incident_package.admin_ui_smoke",
        body_preview="Scout would send this mock alert during a smoke check.",
    )
    app.include_router(
        create_debug_router(
            debug_log=debug_log,
            debug_log_ingestion_channel=DebugEventIngestionChannel.SMOKE_HARNESS,
            message_source=transport,
        )
    )
    app.include_router(create_debug_page_router())
    app.include_router(create_hardware_readiness_router())
    app.include_router(
        create_assistant_router(
            context_resolver=create_assistant_context_resolver(debug_event_log=debug_log),
        )
    )
    return app


def _debug_events() -> list[RuntimeDebugEvent]:
    return [
        _event(
            sequence=1,
            kind="debug_session_started",
            phase="phase35",
            summary="Admin UI smoke replay started.",
            payload={"safety_level": "L0_NORMAL"},
        ),
        _event(
            sequence=2,
            kind="safety_event_emitted",
            phase="phase1",
            summary="Smoke replay emitted a focusable L2 concern event near CP 003.",
            payload={
                "safety_level": "L2_CONCERN",
                "event_type": "route_deviation",
                "checkpoint_id": "cp.003",
                "lat": 24.04682851396501,
                "lon": 121.22322332113981,
                "map_target_ids": ["cp.003", "route-progress"],
            },
            subject_ref="cp.003",
        ),
        _event(
            sequence=3,
            kind="provider_status_recorded",
            phase="phase35",
            summary="Fixture providers are available for visual smoke.",
            payload={
                "provider": "fixture",
                "status": "ok",
                "degraded": False,
            },
        ),
        _event(
            sequence=4,
            kind="debug_session_completed",
            phase="phase35",
            summary="Admin UI smoke replay completed.",
            payload={"safety_level": "L2_CONCERN", "observations_processed": 42},
        ),
    ]


def _event(
    *,
    sequence: int,
    kind: str,
    phase: str,
    summary: str,
    payload: dict,
    subject_ref: str | None = None,
) -> RuntimeDebugEvent:
    return RuntimeDebugEvent(
        event_id=f"debug_event.admin_ui_smoke.{sequence:06d}",
        session_id="debug_session.admin_ui_smoke",
        mission_id="mission.admin_ui_smoke",
        timestamp=f"2026-05-21T08:00:0{sequence}Z",
        sequence=sequence,
        kind=kind,
        source="admin_ui_smoke",
        phase=phase,
        severity="info",
        subject_ref=subject_ref or f"smoke.subject.{sequence}",
        summary=summary,
        payload=payload,
    )


app = create_smoke_app()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve fixture-backed Scout admin UI smoke pages.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=0, type=int)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
