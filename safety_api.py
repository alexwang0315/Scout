from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from checkpoint_manager import CheckpointArrival
from incident_store import IncidentStore
from mission_models import SegmentCapsule
from safety_models import SafetyState


class SafetyAckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requester_id: str
    reason: str
    last_known_route_id: str | None = None


@dataclass(frozen=True)
class SafetyApiSnapshot:
    safety_state: SafetyState
    checkpoint_hits: list[CheckpointArrival] = field(default_factory=list)
    segment_capsules: list[SegmentCapsule] = field(default_factory=list)
    latest_incident_id: str | None = None
    last_known_position: dict[str, Any] | None = None


def snapshot_from_replay_result(replay_result: Any) -> SafetyApiSnapshot:
    latest_package = replay_result.incident_packages[-1] if replay_result.incident_packages else None
    latest_sample = latest_package.raw_samples[-1] if latest_package and latest_package.raw_samples else None
    return SafetyApiSnapshot(
        safety_state=replay_result.safety_state,
        checkpoint_hits=replay_result.checkpoint_hits,
        segment_capsules=replay_result.segment_capsules,
        latest_incident_id=latest_package.incident_id if latest_package else None,
        last_known_position=_position_from_sample(latest_sample),
    )


def create_safety_app(snapshot: SafetyApiSnapshot, incident_store: IncidentStore | None = None) -> FastAPI:
    app = FastAPI(title="Scout Fusion Phase 1 Safety API Mock")
    app.include_router(create_safety_router(snapshot, incident_store))
    return app


def create_safety_router(snapshot: SafetyApiSnapshot, incident_store: IncidentStore | None = None) -> APIRouter:
    router = APIRouter(prefix="/safety", tags=["safety"])

    @router.post("/ack")
    def ack(request: SafetyAckRequest) -> dict[str, Any]:
        latest_incident_id = _latest_incident_id(snapshot, incident_store)
        return {
            "requester_id": request.requester_id,
            "request_reason": request.reason,
            "last_known_route_id": request.last_known_route_id,
            "safety_state": snapshot.safety_state.model_dump(mode="json"),
            "last_known_position": snapshot.last_known_position,
            "latest_incident_id": latest_incident_id,
            "package_available": bool(latest_incident_id and incident_store and incident_store.exists(latest_incident_id)),
            "battery": {"status": "unknown"},
            "signal": {"status": "unknown"},
        }

    @router.get("/state")
    def state() -> dict[str, Any]:
        transitions = snapshot.safety_state.transitions
        return {
            "safety_state": snapshot.safety_state.model_dump(mode="json"),
            "latest_transition": transitions[-1].model_dump(mode="json") if transitions else None,
            "active_risk_reasons": [event.reason for event in snapshot.safety_state.active_events],
            "latest_incident_id": _latest_incident_id(snapshot, incident_store),
        }

    @router.get("/incidents/{incident_id}")
    def incident(incident_id: str) -> dict[str, Any]:
        if incident_store is None or not incident_store.exists(incident_id):
            raise HTTPException(status_code=404, detail="Incident package not found")
        return incident_store.load(incident_id).model_dump(mode="json")

    @router.get("/checkins")
    def checkins() -> dict[str, Any]:
        return {
            "checkins": [_checkpoint_arrival_dump(arrival) for arrival in snapshot.checkpoint_hits],
            "segment_capsules": [capsule.model_dump(mode="json") for capsule in snapshot.segment_capsules],
        }

    @router.get("/capsules/{capsule_id}")
    def capsule(capsule_id: str) -> dict[str, Any]:
        for segment_capsule in snapshot.segment_capsules:
            if segment_capsule.capsule_id == capsule_id:
                return segment_capsule.model_dump(mode="json")
        raise HTTPException(status_code=404, detail="Segment capsule not found")

    return router


def _latest_incident_id(snapshot: SafetyApiSnapshot, incident_store: IncidentStore | None) -> str | None:
    if snapshot.latest_incident_id:
        return snapshot.latest_incident_id
    if incident_store is None:
        return None
    ids = incident_store.list_ids()
    return ids[-1] if ids else None


def _checkpoint_arrival_dump(arrival: CheckpointArrival) -> dict[str, Any]:
    return {
        "checkpoint": arrival.checkpoint.model_dump(mode="json"),
        "distance_m": arrival.distance_m,
        "segment_capsule": arrival.segment_capsule.model_dump(mode="json") if arrival.segment_capsule else None,
    }


def _position_from_sample(sample: dict[str, Any] | None) -> dict[str, Any] | None:
    if sample is None:
        return None
    return {
        "timestamp": sample.get("timestamp"),
        "lat": sample.get("lat"),
        "lon": sample.get("lon"),
        "elevation_m": sample.get("elevation_m"),
        "gps_horizontal_accuracy_m": sample.get("gps_horizontal_accuracy_m"),
    }
