"""Typed, candidate-only commands for composing a planned hiking itinerary."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlannedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TrailPathSelection(PlannedModel):
    start_anchor_id: str
    end_anchor_id: str
    via_anchor_ids: list[str] = Field(default_factory=list)


class RouteSegmentSelection(PlannedModel):
    """Inclusive source point range; a selection never crosses a GPX trkseg."""

    source_id: str = ""
    part_index: int = Field(default=0, ge=0)
    start_index: int = Field(default=0, ge=0)
    end_index: int | None = Field(default=None, ge=0)
    round_trip: bool = False
    trail_search: TrailPathSelection | None = None


class ItineraryOperation(PlannedModel):
    kind: Literal["branch", "replace", "trim", "stop", "camp", "depart", "deadline"]
    at: str | None = None
    to: str | None = None
    visit: int | None = Field(default=None, ge=1)
    to_visit: int | None = Field(default=None, ge=1)
    selection: RouteSegmentSelection | None = None
    duration_minutes: float | None = Field(default=None, ge=0)
    departure_at: datetime | None = None
    latest_arrival_at: datetime | None = None
    label: str | None = None
    source_text: str | None = None

    @field_validator("departure_at", "latest_arrival_at")
    @classmethod
    def aware_operation_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Use an ISO date/time with an explicit timezone offset.")
        return value


class PlannedRouteRequest(PlannedModel):
    human_text: str = ""
    source_snapshot_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    parent_version_id: str | None = Field(default=None, pattern=r"^plan\.[a-f0-9]{16,64}$")
    departure_at: datetime | None = None
    default_speed_kmh: float | None = Field(default=None, gt=0, le=20)
    pace_mode: Literal["source_preferred", "fixed_speed"] = "source_preferred"
    name_resolutions: dict[str, str] = Field(default_factory=dict)
    operations: list[ItineraryOperation] = Field(default_factory=list)
    route_selections: list[RouteSegmentSelection] = Field(default_factory=list)

    @field_validator("departure_at")
    @classmethod
    def aware_departure(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Use an ISO departure date/time with an explicit timezone offset.")
        return value


class PlannedRouteConflict(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
