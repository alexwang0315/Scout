from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_risk.cp.dictionaries import HAZARD_BASE_SCORES, HAZARD_KEYWORDS

DEFAULT_CONFIG_PACKAGE = "scout_risk.configs"
DEFAULT_CONFIG_NAME = "terrain_risk_profile.default.toml"


class TerrainConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoutePreparationConfig(TerrainConfigModel):
    sample_interval_m: float = Field(default=20.0, gt=0)
    overpass_corridor_m: float = Field(default=35.0, gt=0)
    overpass_reference_interval_m: float = Field(default=20.0, gt=0)
    dem_buffer_m: float = Field(default=140.0, ge=0)
    dtm_pixel_size_m: float = Field(default=20.0, gt=0)


class TerrainFeatureConfig(TerrainConfigModel):
    radius_m: float = Field(default=100.0, gt=0)
    slope_score_scale_degrees: float = Field(default=45.0, gt=0)
    downhill_drop_score_scale_m: float = Field(default=100.0, gt=0)
    local_relief_score_scale_m: float = Field(default=150.0, gt=0)
    contour_density_relief_score_scale_m: float = Field(default=100.0, gt=0)


class TeiiConfig(TerrainConfigModel):
    base_weight: float = Field(default=0.70, ge=0)
    peak_weight: float = Field(default=0.30, ge=0)
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "slope_macro": 0.25,
            "downhill_drop_100m": 0.25,
            "local_relief_100m": 0.20,
            "contour_density": 0.15,
            "slope_continuity": 0.15,
        }
    )

    @model_validator(mode="after")
    def validate_weights(self) -> "TeiiConfig":
        required = {
            "slope_macro",
            "downhill_drop_100m",
            "local_relief_100m",
            "contour_density",
            "slope_continuity",
        }
        missing = sorted(required - set(self.weights))
        if missing:
            raise ValueError(f"missing TEII weights: {', '.join(missing)}")
        if any(weight < 0 for weight in self.weights.values()):
            raise ValueError("TEII weights must be non-negative")
        if self.base_weight + self.peak_weight <= 0:
            raise ValueError("TEII base_weight + peak_weight must be positive")
        return self


class RouteRiskScoringConfig(TerrainConfigModel):
    cp_radius_m: float = Field(default=60.0, gt=0)
    lec_radius_m: float = Field(default=40.0, gt=0)
    lec_percentile: float = Field(default=90.0, ge=0, le=100)
    tri_radius_cells: int = Field(default=2, ge=0)
    tri_high_threshold: float = Field(default=70.0, ge=0, le=100)
    tri_high_ratio_weight: float = Field(default=0.60, ge=0)
    tri_mean_weight: float = Field(default=0.40, ge=0)
    sri_previous_sample_count: int = Field(default=3, ge=1)
    sri_scale: float = Field(default=50.0, gt=0)
    terrain_blend_teii_weight: float = Field(default=0.65, ge=0)
    terrain_blend_tri_weight: float = Field(default=0.20, ge=0)
    terrain_blend_sri_weight: float = Field(default=0.10, ge=0)
    terrain_blend_lec_weight: float = Field(default=0.05, ge=0)
    terrain_risk_floor_to_teii: bool = True
    pretrip_terrain_weight: float = Field(default=0.80, ge=0)
    pretrip_scp_weight: float = Field(default=0.20, ge=0)
    risk_level_thresholds: list[float] = Field(
        default_factory=lambda: [20.0, 40.0, 60.0, 80.0],
        min_length=4,
        max_length=4,
    )
    teii_extreme_threshold: float = Field(default=80.0, ge=0, le=100)
    teii_low_tolerance_threshold: float = Field(default=60.0, ge=0, le=100)
    teii_caution_threshold: float = Field(default=40.0, ge=0, le=100)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "RouteRiskScoringConfig":
        thresholds = self.risk_level_thresholds
        if thresholds != sorted(thresholds):
            raise ValueError("risk_level_thresholds must be ascending")
        if thresholds[0] < 0 or thresholds[-1] > 100:
            raise ValueError("risk_level_thresholds must stay within 0-100")
        if not (
            self.teii_extreme_threshold
            >= self.teii_low_tolerance_threshold
            >= self.teii_caution_threshold
        ):
            raise ValueError("TEII explanation thresholds must be descending")
        if self.pretrip_terrain_weight + self.pretrip_scp_weight <= 0:
            raise ValueError("pretrip risk weights must be positive")
        return self


class SCPConfig(TerrainConfigModel):
    keyword_bonus_per_extra_keyword: float = Field(default=3.0, ge=0)
    keyword_bonus_cap: float = Field(default=10.0, ge=0)
    located_confidence: float = Field(default=1.0, ge=0, le=1)
    missing_location_confidence: float = Field(default=0.75, ge=0, le=1)
    hazard_base_scores: dict[str, float] = Field(
        default_factory=lambda: dict(HAZARD_BASE_SCORES)
    )

    @model_validator(mode="after")
    def validate_scores(self) -> "SCPConfig":
        if any(score < 0 or score > 100 for score in self.hazard_base_scores.values()):
            raise ValueError("hazard base scores must stay within 0-100")
        return self


class TerrainRiskProfileConfig(TerrainConfigModel):
    schema_version: str = "scout_risk.terrain_risk_profile_config.v1"
    route_preparation: RoutePreparationConfig = Field(
        default_factory=RoutePreparationConfig
    )
    terrain_features: TerrainFeatureConfig = Field(default_factory=TerrainFeatureConfig)
    teii: TeiiConfig = Field(default_factory=TeiiConfig)
    route_risk: RouteRiskScoringConfig = Field(default_factory=RouteRiskScoringConfig)
    scp: SCPConfig = Field(default_factory=SCPConfig)
    cp_note_keywords: dict[str, list[str]] = Field(
        default_factory=lambda: {key: list(value) for key, value in HAZARD_KEYWORDS.items()}
    )

    @model_validator(mode="after")
    def validate_cp_scores(self) -> "TerrainRiskProfileConfig":
        missing_scores = sorted(set(self.cp_note_keywords) - set(self.scp.hazard_base_scores))
        if missing_scores:
            raise ValueError(
                "cp_note_keywords contains hazards without SCP scores: "
                + ", ".join(missing_scores)
            )
        return self


@dataclass(frozen=True)
class LoadedTerrainRiskConfig:
    config: TerrainRiskProfileConfig
    source: str
    sha256: str

    def metadata(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "sha256": self.sha256,
            "schema_version": self.config.schema_version,
            "parameters": self.config.model_dump(mode="json"),
        }


def load_terrain_risk_config(path: str | Path | None = None) -> LoadedTerrainRiskConfig:
    if path is None:
        source = f"package:{DEFAULT_CONFIG_PACKAGE}/{DEFAULT_CONFIG_NAME}"
        raw = (
            files(DEFAULT_CONFIG_PACKAGE)
            .joinpath(DEFAULT_CONFIG_NAME)
            .read_bytes()
        )
    else:
        config_path = Path(path)
        source = str(config_path)
        raw = config_path.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    return LoadedTerrainRiskConfig(
        config=TerrainRiskProfileConfig.model_validate(data),
        source=source,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
