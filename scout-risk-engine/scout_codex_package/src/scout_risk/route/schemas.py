from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RiskConfidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dem_resolution: str = "20m"
    teii_confidence: str = "medium"
    wci_confidence: str = "low_or_unavailable"
    scp_confidence: str = "low"


class RouteRiskSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str
    sample_id: str
    distance_m: float = Field(ge=0)
    lat: float | None = None
    lon: float | None = None
    x: float | None = None
    y: float | None = None
    elevation_m: float | None = None
    teii_20m: float = Field(ge=0, le=100)
    tri: float = Field(ge=0, le=100)
    sri: float = Field(ge=0, le=100)
    lec: float = Field(ge=0, le=100)
    scp: float = Field(ge=0, le=100)
    pretrip_risk: float = Field(ge=0, le=100)
    risk_level: int = Field(ge=1, le=5)
    hazard_types: list[str] = Field(default_factory=list)
    confidence: RiskConfidence = Field(default_factory=RiskConfidence)
    explanation: list[str] = Field(default_factory=list)

