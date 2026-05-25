from __future__ import annotations

from scout_risk.cp.parser import ParsedCPNote
from scout_risk.terrain_config import SCPConfig


def compute_scp(note: ParsedCPNote, *, config: SCPConfig | None = None) -> float:
    config = config or SCPConfig()
    if not note.hazard_types:
        return 0.0
    base = max(config.hazard_base_scores.get(hazard, 0.0) for hazard in note.hazard_types)
    keyword_bonus = min(
        config.keyword_bonus_cap,
        max(0, len(note.matched_keywords) - 1)
        * config.keyword_bonus_per_extra_keyword,
    )
    location_confidence = (
        config.located_confidence
        if note.lat is not None and note.lon is not None
        else config.missing_location_confidence
    )
    return clamp_score((base + keyword_bonus) * location_confidence)


def clamp_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))
