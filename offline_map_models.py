from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MapSourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    source_version: str
    confidence: float = Field(ge=0.0, le=1.0)
    last_verified_at: str | None = None
    known_staleness_risk: Literal["low", "medium", "high"] = "medium"


class MapCoordinate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float
    lon: float


class TrailCorridor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corridor_id: str
    name: str
    coordinates: list[MapCoordinate]
    corridor_half_width_m: float = Field(default=3.0, gt=0.0)
    route_level: str | None = None
    source_metadata: MapSourceMetadata


class HazardZone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hazard_id: str
    hazard_type: str
    name: str
    polygon: list[MapCoordinate]
    l2_duration_s: float = Field(default=30.0, gt=0.0)
    source_metadata: MapSourceMetadata


class MapPoi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poi_id: str
    poi_type: str
    name: str
    coordinate: MapCoordinate
    source_metadata: MapSourceMetadata


class CorridorEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inside: bool
    corridor_id: str | None = None
    distance_m: float
    allowed_distance_m: float
    source_metadata: MapSourceMetadata | None = None


class HazardEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hazard_id: str
    hazard_type: str
    name: str
    l2_duration_s: float
    source_metadata: MapSourceMetadata
