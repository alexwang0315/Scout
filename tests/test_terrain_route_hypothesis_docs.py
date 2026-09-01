from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRH_SPEC = ROOT / "docs" / "specs" / "scout-terrain-route-hypothesis.md"
OUTDOOR_STANDARD = (
    ROOT / "docs" / "specs" / "SCOUT_OUTDOOR_AI_AGENT_STANDARD.md"
)


def test_trh_spec_preserves_candidate_authority_and_resolution_unknowns() -> None:
    spec = TRH_SPEC.read_text(encoding="utf-8")

    for contract in (
        "authority=candidate_only",
        "source_type=terrain_hypothesis",
        "runtime_safety_truth=false",
        "operational=false",
        "promotion_allowed=false",
        "safe_or_walkable=not_determined",
        "CANDIDATE / TERRAIN HYPOTHESIS / NOT A VERIFIED TRAIL",
        "macro_terrain_only",
        "vegetation_unknown",
        "microterrain_unknown",
        "recent_landslide_unknown",
        "legal_access_unknown",
        "Scout-host execution",
    ):
        assert contract in spec

    assert "C_corridor(x,y) = C_A(x,y) + C_B(x,y) - C_AB" in spec
    assert "best-path cells are never unioned into a corridor mask" in spec
    assert "Actual execution on the Scout host remains `UNKNOWN`" in spec


def test_navigation_force_standard_defines_trh_as_non_operational_evidence() -> None:
    standard = OUTDOOR_STANDARD.read_text(encoding="utf-8")
    section = standard.split(
        "### 11.11 Terrain Route Hypothesis：任意 A/B 地形候選",
        1,
    )[1].split("\n---\n", 1)[0]

    for contract in (
        "不得稱為 Trail Generator",
        "authority=candidate_only",
        "source_type=terrain_hypothesis",
        "runtime_safety_truth=false",
        "safe_or_walkable=not_determined",
        "原子發布",
        "20 m DEM",
        "`UNKNOWN`",
        "不得授權 Scout 依 TRH",
        "自動做前進、撤退、改線",
        "[Scout Terrain Route Hypothesis Engine](scout-terrain-route-hypothesis.md)",
    ):
        assert contract in section
