from __future__ import annotations

from scout_risk.cp.parser import CPNote, parse_cp_notes
from scout_risk.cp.scp import compute_scp


def test_cp_note_parser_classifies_required_hazard_keywords():
    text = "大崩壁崩塌，需高繞，有拉繩，危崖瘦稜，路跡不明，經溪溝"

    parsed = parse_cp_notes([CPNote(lat=24.0, lon=121.0, text=text)])[0]

    assert set(parsed.hazard_types) >= {
        "collapse",
        "reroute",
        "climbing",
        "exposure",
        "navigation",
        "valley_water",
    }
    assert "大崩壁" in parsed.matched_keywords
    assert "崩塌" in parsed.matched_keywords
    assert compute_scp(parsed) == 100.0


def test_cp_note_without_location_has_lower_but_clamped_scp():
    parsed = parse_cp_notes([CPNote(lat=None, lon=None, text="崩塌路段")])[0]

    assert parsed.hazard_types == ["collapse"]
    assert 0.0 <= compute_scp(parsed) <= 100.0
    assert compute_scp(parsed) < 95.0

