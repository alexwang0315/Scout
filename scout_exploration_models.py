"""Explicit intake contracts for a workspace whose reference tracks are empty."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pretrip_models import DtmRasterSource


class ExplorationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _transform(x: float, y: float, source: str, target: str) -> tuple[float, float]:
    if source == target:
        return x, y
    if source == "EPSG:4326" and target == "EPSG:3826":
        from pretrip_source_ingest import wgs84_to_twd97
        return wgs84_to_twd97(y, x)
    from osgeo import osr
    source_srs, target_srs = osr.SpatialReference(), osr.SpatialReference()
    for srs, code in ((source_srs, source), (target_srs, target)):
        srs.ImportFromEPSG(int(code.split(":")[1]))
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    values = osr.CoordinateTransformation(source_srs, target_srs).TransformPoint(x, y)
    if not all(math.isfinite(value) for value in values[:2]):
        raise ValueError("Coordinate transform failed")
    return float(values[0]), float(values[1])


class ExplorationPoint(ExplorationModel):
    x: float
    y: float
    crs: Literal["EPSG:4326", "EPSG:3826"]
    label: str | None = None

    @model_validator(mode="after")
    def valid_location(self):
        lon, lat = self.wgs84()
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("Point is outside WGS84 bounds")
        if self.crs == "EPSG:3826" and not (118 <= lon <= 124 and 20 <= lat <= 27):
            raise ValueError("TWD97 point is outside the supported Taiwan extent")
        return self

    def wgs84(self) -> tuple[float, float]:
        return _transform(self.x, self.y, self.crs, "EPSG:4326")


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(p, a, b):
    return abs(_cross(a, b, p)) <= 1e-9 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _intersects(a, b, c, d):
    values = (_cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b))
    return ((values[0] * values[1] < 0 and values[2] * values[3] < 0)
            or _on_segment(c, a, b) or _on_segment(d, a, b)
            or _on_segment(a, c, d) or _on_segment(b, c, d))


class ExplorationAOI(ExplorationModel):
    """One declared coordinate system and either a bbox or a closed simple ring."""
    crs: Literal["EPSG:4326", "EPSG:3826"]
    bbox: tuple[float, float, float, float] | None = None
    polygon: list[tuple[float, float]] | None = None

    @model_validator(mode="after")
    def valid_area(self):
        if (self.bbox is None) == (self.polygon is None):
            raise ValueError("AOI requires exactly one bbox or polygon")
        if self.bbox is not None:
            left, bottom, right, top = self.bbox
            if left >= right or bottom >= top:
                raise ValueError("AOI bbox must have positive width and height")
        ring = self.ring()
        if len(ring) < 4 or ring[0] != ring[-1] or len(set(ring[:-1])) < 3:
            raise ValueError("AOI polygon must be a closed ring of at least three vertices")
        if any(a == b for a, b in zip(ring, ring[1:])):
            raise ValueError("AOI polygon repeats consecutive vertices")
        if abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))) <= 1e-12:
            raise ValueError("AOI polygon has zero area")
        edges = list(zip(ring, ring[1:]))
        for index, (a, b) in enumerate(edges):
            for other, (c, d) in enumerate(edges[index + 1:], index + 1):
                if other != index + 1 and not (index == 0 and other == len(edges) - 1) and _intersects(a, b, c, d):
                    raise ValueError("AOI polygon intersects itself")
        for x, y in ring:
            ExplorationPoint(x=x, y=y, crs=self.crs)
        return self

    def ring(self, target_crs: str | None = None) -> list[tuple[float, float]]:
        if self.bbox is not None:
            left, bottom, right, top = self.bbox
            points = [(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)]
        else:
            points = list(self.polygon or [])
        return [_transform(x, y, self.crs, target_crs or self.crs) for x, y in points]

    def bbox_wgs84(self) -> dict[str, float]:
        ring = self.ring("EPSG:4326")
        return {"west": min(p[0] for p in ring), "east": max(p[0] for p in ring),
                "south": min(p[1] for p in ring), "north": max(p[1] for p in ring)}

    def contains(self, point: ExplorationPoint) -> bool:
        p = _transform(point.x, point.y, point.crs, self.crs)
        ring = self.ring()
        inside = False
        for a, b in zip(ring, ring[1:]):
            if _on_segment(p, a, b):
                return True
            if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
                inside = not inside
        return inside


class ExplorationWaypoint(ExplorationModel):
    label: str = Field(min_length=1)
    point: ExplorationPoint | None = None
    day: int | None = Field(default=None, ge=1)
    purpose: Literal["passage", "camp_candidate", "research"] = "passage"


class ExplorationLimits(ExplorationModel):
    days: int | None = Field(default=None, ge=1)
    departure_at: datetime | None = None
    latest_arrival_at: datetime | None = None
    max_daily_walk_hours: float | None = Field(default=None, gt=0, le=24)
    fixed_speed_kmh: float | None = Field(default=None, gt=0, le=20)
    speed_range_kmh: tuple[float, float] | None = None
    fixed_rest_minutes: float | None = Field(default=None, ge=0)
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("departure_at", "latest_arrival_at")
    @classmethod
    def aware_time(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("Exploration times require an explicit timezone")
        return value

    @model_validator(mode="after")
    def valid_limits(self):
        if self.speed_range_kmh is not None and not 0 < self.speed_range_kmh[0] <= self.speed_range_kmh[1] <= 20:
            raise ValueError("Speed range must be positive and ordered")
        if self.departure_at and self.latest_arrival_at and self.latest_arrival_at <= self.departure_at:
            raise ValueError("Arrival limit must follow departure")
        return self


class ExplorationPreparationInputs(ExplorationModel):
    dtm_dirs: list[str] = Field(default_factory=list)
    dtm_rasters: list[DtmRasterSource] = Field(default_factory=list)


class ExplorationWorkspaceRequest(ExplorationModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    intent: str = Field(min_length=1)
    aoi: ExplorationAOI
    start: ExplorationPoint | None = None
    destination: ExplorationPoint | None = None
    waypoints: list[ExplorationWaypoint] = Field(default_factory=list)
    limits: ExplorationLimits = Field(default_factory=ExplorationLimits)
    preparation_inputs: ExplorationPreparationInputs = Field(default_factory=ExplorationPreparationInputs)
    requested_by: str = Field(default="human", min_length=1)

    @field_validator("intent", "requested_by")
    @classmethod
    def nonempty_text(cls, value):
        if not value.strip():
            raise ValueError("A non-empty explicit value is required")
        return value.strip()

    @model_validator(mode="after")
    def valid_targets(self):
        for point in (self.start, self.destination, *(w.point for w in self.waypoints)):
            if point is not None and not self.aoi.contains(point):
                raise ValueError("A/B and located waypoints must lie inside the AOI")
        if self.start and self.destination and self.start.wgs84() == self.destination.wgs84():
            raise ValueError("A/B must be distinct; omit unknown endpoints for area research")
        if any(w.day and self.limits.days and w.day > self.limits.days for w in self.waypoints):
            raise ValueError("Waypoint day exceeds the declared trip days")
        return self
