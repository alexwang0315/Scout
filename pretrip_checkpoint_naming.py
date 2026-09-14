"""Source-backed display names for unchanged pretrip checkpoint candidates."""
from __future__ import annotations

import html
import math
import re
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from geo_utils import haversine_m
from pretrip_models import PreTripCheckpointCandidate
from pretrip_route_note_candidates import RouteNoteCandidateSet
from route_matching import GpxRoute

POLICY_VERSION = "scout.checkpoint_naming.v1"
REPORT_REF = "outputs/checkpoint_naming.json"
MAX_NOTE_DISTANCE_M = 50.0
MAX_PROGRESS_DELTA_M = 75.0
MAX_ELEVATION_DELTA_M = 60.0
_GENERIC = re.compile(
    r"(?:cp[\s._-]*\d+|w(?:ay)?p(?:oint|t)?[\s._-]*\d+|\d+|"
    r"start|finish|rest area / camp area \d+|c\d+(?:[=/-]c?\d+)*|"
    r"h?\s*\d+(?:\.\d+)?\s*(?:m|k|km|公尺|公里)?)", re.I,
)
_FEATURE = re.compile(
    r"駐在所|營盤|遺址|登山口|山屋|山莊|吊橋|橋頭|溪溝|支流|匯流|渡溪|過溪|"
    r"石階|駁坎|平台|營地|營位|水源|水塘|瀑布|鞍部|寬鞍|稜線|寬稜|瘦稜|"
    r"轉稜|接稜|上稜|越稜|岔路|叉路|路口|交會|交界|崩壁|崩塌|崩溝|岩壁|"
    r"巨石|大石|倒木|神木|樹洞|哨崗|家屋|岩洞|獵寮|工寮|草原|草坡|竹林|"
    r"樹林|山頭|山頂|三角點|上切|下切|高繞|腰繞|拉繩|陡坡|緩坡|河階|"
    r"古道|吊橋|溪床|乾溪|活水|伏流水|黑水|湖|池|峰|鞍|溪|橋|營(?:$|[（(])"
)
_DIRECTION = re.compile(r"左|右|上切|下切|高繞|腰繞|轉稜|接稜|上稜")


class NamingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    original_label: str
    label: str
    basis: Literal[
        "manual_name", "preserved_existing_name", "trusted_gpx_name",
        "corroborated_gpx_name", "note_description", "elevation_feature", "mileage",
    ]
    progress_m: float
    elevation_m: float | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    disambiguated: bool = False
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


def _plain(value: str) -> str:
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", value, flags=re.I | re.S)
    value = re.sub(r"<br\s*/?>|</(?:p|div|h\d)>", "；", value, flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", value))).strip()


def is_generated_name(value: str) -> bool:
    text = _plain(value)
    return not text or bool(_GENERIC.fullmatch(text))


def _place_description(value: str) -> str | None:
    text = _plain(value)
    # Exporter counters are not elevations: only strip a leading zero counter.
    text = re.sub(r"^0\d{1,3}[\s._-]*(?=[\u3400-\u9fff])", "", text)
    for clause in re.split(r"[；;。\n|]", text):
        clause = clause.strip(" ，,：:")
        if re.fullmatch(r"[\u3400-\u9fff]+(?:縣|市)[\u3400-\u9fff]+(?:鄉|鎮|區|市)", clause):
            continue
        if re.search(r"開始時間|結束時間|平均速度|最高海拔|最低海拔|移動時間|Segment:", clause, re.I):
            continue
        if 1 < len(clause) <= 32 and not is_generated_name(clause) and _FEATURE.search(clause):
            return clause
    return None


def _usable_original(value: str) -> bool:
    value = _plain(value)
    return (
        1 < len(value) <= 32 and not is_generated_name(value)
        and not re.match(r"^0\d{1,3}", value)
        and not re.search(r"[；;。<>]|開始時間|平均速度", value)
        and not re.fullmatch(r"[\u3400-\u9fff]+(?:縣|市)[\u3400-\u9fff]+(?:鄉|鎮|區|市)", value)
        and bool(
            _FEATURE.search(value)
            or re.fullmatch(r"[A-Za-z][A-Za-z '-]{2,31}", value)
            or re.fullmatch(r"[\u3400-\u9fff]{2,16}", value)
        )
    )


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _project_notes(route: GpxRoute, note_sets: list[RouteNoteCandidateSet]) -> list[dict[str, Any]]:
    # A small spatial index avoids a full route scan for every waypoint. Matching
    # still uses metres and route progress, never just the closest CP ID.
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    cell = 0.001
    for i, point in enumerate(route.points):
        grid[(math.floor(point.lat / cell), math.floor(point.lon / cell))].append(i)
    projected = []
    for source in note_sets:
        for note in source.candidates:
            x, y = math.floor(note.lat / cell), math.floor(note.lon / cell)
            nearby = []
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    for i in grid.get((x + dx, y + dy), ()):
                        point = route.points[i]
                        distance = haversine_m(note.lat, note.lon, point.lat, point.lon)
                        if distance <= MAX_NOTE_DISTANCE_M:
                            nearby.append((distance, i))
            if not nearby:
                continue
            distance, index = min(nearby)
            progress = route.points[index].progress_m
            # Repeated passes / parallel branches without an occurrence anchor
            # are ambiguous; do not silently attach the label to either pass.
            if any(d <= distance + 10 and abs(route.points[i].progress_m - progress) > 150 for d, i in nearby):
                continue
            projected.append({
                "note": note, "source_sha256": source.source_sha256,
                "source_uri": source.source_uri, "progress_m": progress,
                "route_offset_m": distance,
            })
    return projected


def _old_name(
    checkpoint: PreTripCheckpointCandidate,
    previous: dict[str, Any] | None,
    reviews: list[dict[str, Any]],
) -> tuple[str, str, list[dict[str, Any]]] | None:
    if not previous or previous.get("route_point_index") != checkpoint.route_point_index:
        return None
    if haversine_m(checkpoint.lat, checkpoint.lon, previous["lat"], previous["lon"]) > 5:
        return None
    matching = [r for r in reviews if r.get("reviewed_ref_kind") == "checkpoint" and r.get("reviewed_ref") == checkpoint.candidate_id]
    latest = matching[-1] if matching else None
    if latest and latest.get("decision") == "rejected":
        return None
    label = previous.get("label", "")
    if latest and latest.get("decision") == "corrected":
        label = (latest.get("correction") or {}).get("payload", {}).get("label", label)
    if is_generated_name(label):
        return None
    old_naming = next((a for a in previous.get("source_attribution", []) if a.get("source_kind") == "checkpoint_naming"), None)
    if latest and latest.get("decision") in {"accepted", "corrected"}:
        return label, "manual_name", [{"source_ref": REPORT_REF, "review_id": latest["review_id"], "source_review": latest}]
    if old_naming:
        # Recompute our previous automatic decisions; never promote them to
        # human confirmation just because they survived an import.
        if old_naming.get("basis") not in {"manual_name", "preserved_existing_name"}:
            return None
        return label, old_naming["basis"], old_naming.get("evidence", [])
    return label, "preserved_existing_name", [{"source_ref": "candidates/checkpoints.json", "manual_confirmation_recorded": False}]


def _fallback(route: GpxRoute, checkpoint: PreTripCheckpointCandidate) -> tuple[str, str, list[dict[str, Any]]]:
    point = route.points[checkpoint.route_point_index]
    elevation = point.elevation_m
    kind = {"start": "起點", "finish": "終點", "rest_area": "停留點"}.get(checkpoint.checkpoint_type)
    evidence: dict[str, Any] = {"source_ref": checkpoint.source_refs[0] if checkpoint.source_refs else str(route.source), "route_point_index": checkpoint.route_point_index, "elevation_source": "gpx_ele"}
    if kind == "停留點":
        evidence["feature_source"] = "gpx_stop_cluster_not_confirmed_campsite"
    if not kind and _finite(elevation):
        progress = [p.progress_m for p in route.points]
        lo = max(0, bisect_left(progress, point.progress_m - 50))
        hi = min(len(progress) - 1, bisect_left(progress, point.progress_m + 50))
        start, end = route.points[lo], route.points[hi]
        span = end.progress_m - start.progress_m
        if 30 <= span <= 150 and _finite(start.elevation_m) and _finite(end.elevation_m):
            grade = (end.elevation_m - start.elevation_m) / span
            kind = "上坡段" if grade >= 0.08 else "下坡段" if grade <= -0.08 else "緩坡段"
            evidence.update(feature_source="gpx_local_grade", grade=round(grade, 4), direction_frame="primary_route_order", route_index_range=[lo, hi])
    if kind and _finite(elevation):
        # The imported GPX elevation is not a surveyed height or DEM contour.
        return f"H約{round(elevation / 10) * 10:.0f}{kind}", "elevation_feature", [evidence]
    return f"{point.progress_m / 1000:.2f}K{kind or '路點'}", "mileage", [evidence]


def name_checkpoints(
    route: GpxRoute,
    checkpoints: list[PreTripCheckpointCandidate],
    note_sets: list[RouteNoteCandidateSet],
    *,
    previous_checkpoints: list[dict[str, Any]] | None = None,
    reviews: list[dict[str, Any]] | None = None,
    trusted_source_sha256s: tuple[str, ...] = (),
) -> tuple[list[PreTripCheckpointCandidate], dict[str, Any]]:
    previous = {cp["candidate_id"]: cp for cp in previous_checkpoints or []}
    projected = _project_notes(route, note_sets)
    decisions = []
    for cp in checkpoints:
        if cp.route_point_index is None or cp.route_point_index >= len(route.points):
            raise ValueError(f"checkpoint lacks a valid route anchor: {cp.candidate_id}")
        point = route.points[cp.route_point_index]
        selected = _old_name(cp, previous.get(cp.candidate_id), reviews or [])
        options = []
        for item in projected:
            note = item["note"]
            offset = haversine_m(cp.lat, cp.lon, note.lat, note.lon)
            delta = abs(item["progress_m"] - point.progress_m)
            if offset > MAX_NOTE_DISTANCE_M or delta > MAX_PROGRESS_DELTA_M:
                continue
            # Zero is commonly an export sentinel in historical Taiwanese GPX.
            if _finite(note.ele_m) and note.ele_m != 0 and _finite(point.elevation_m) and abs(note.ele_m - point.elevation_m) > MAX_ELEVATION_DELTA_M:
                continue
            original = _plain(note.name)
            support = {item["source_sha256"]}
            if _usable_original(original):
                for other in projected:
                    peer = other["note"]
                    if _plain(peer.name) == original and abs(other["progress_m"] - item["progress_m"]) <= 50 and haversine_m(note.lat, note.lon, peer.lat, peer.lon) <= 30:
                        support.add(other["source_sha256"])
            if _usable_original(original) and (item["source_sha256"] in trusted_source_sha256s or len(support) >= 2):
                label, field = original, "name"
                basis = "trusted_gpx_name" if item["source_sha256"] in trusted_source_sha256s else "corroborated_gpx_name"
                rank = 0
            else:
                parts = [(field, _place_description(getattr(note, field))) for field in ("cmt", "desc", "name")]
                found = next(((field, value) for field, value in parts if value), None)
                if not found:
                    continue
                field, label = found
                basis, rank = "note_description", 1
            if offset > 20:
                label += "附近"
            evidence = {
                "source_ref": note.source_refs[0] if note.source_refs else item["source_uri"],
                "source_uri": item["source_uri"], "source_sha256": item["source_sha256"],
                "source_waypoint_index": note.source_waypoint_index,
                "source_field": field, "raw_name": note.name, "raw_cmt": note.cmt, "raw_desc": note.desc,
                "distance_m": round(offset, 2), "progress_delta_m": round(delta, 2),
                "source_time": note.time, "source_freshness": note.route_note_freshness,
                "supporting_source_sha256s": sorted(support),
                "reliability_scope": "cross_file_name_agreement_not_field_verification" if len(support) >= 2 else "source_note_only",
                "direction_frame": "source_note_not_navigation_instruction" if _DIRECTION.search(label) else "place_description",
            }
            options.append((rank, offset, delta, item["source_sha256"], note.source_waypoint_index, label, basis, evidence))
        if selected is None:
            if options:
                choice = min(options, key=lambda row: row[:5])
                selected = choice[5], choice[6], [choice[7]]
            else:
                selected = _fallback(route, cp)
        label, basis, evidence = selected
        decisions.append(NamingDecision(candidate_id=cp.candidate_id, original_label=cp.label, label=label, basis=basis, progress_m=point.progress_m, elevation_m=point.elevation_m if _finite(point.elevation_m) else None, evidence=evidence))
    groups = Counter(d.label for d in decisions)
    for decision in decisions:
        if groups[decision.label] > 1 and decision.basis not in {"manual_name", "preserved_existing_name"}:
            decision.label += f" · {decision.progress_m / 1000:.3f}K"
            decision.disambiguated = True
    named = []
    for cp, decision in zip(checkpoints, decisions):
        attribution = {"source_kind": "checkpoint_naming", "source_ref": REPORT_REF, "policy_version": POLICY_VERSION, **decision.model_dump(mode="json")}
        named.append(cp.model_copy(update={
            "label": decision.label,
            "source_refs": list(dict.fromkeys([*cp.source_refs, REPORT_REF])),
            "source_attribution": [a for a in cp.source_attribution if a.get("source_kind") != "checkpoint_naming"] + [attribution],
        }))
    return named, {
        "schema_version": POLICY_VERSION, "artifact_kind": "pretrip_checkpoint_naming",
        "candidate_only": True, "runtime_safety_truth": False,
        "policy": {"priority": ["manual_or_reliable_original", "note_description", "elevation_feature", "mileage"], "max_note_distance_m": MAX_NOTE_DISTANCE_M, "max_progress_delta_m": MAX_PROGRESS_DELTA_M, "max_elevation_delta_m": MAX_ELEVATION_DELTA_M, "elevation_source": "gpx_ele_rounded_to_10m_not_contour", "trusted_source_sha256s": list(trusted_source_sha256s)},
        "counts": dict(Counter(d.basis for d in decisions)),
        "checkpoint_count": len(named),
        "decisions": [d.model_dump(mode="json") for d in decisions],
    }


def load_previous_naming(project_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import json

    def read(ref: str, default: Any) -> Any:
        path = (project_root / ref).resolve()
        path.relative_to(project_root.resolve())
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default

    project = read("project.json", {})
    checkpoints = read(project.get("checkpoint_candidates_ref", "candidates/checkpoints.json"), [])
    reviews = read(project.get("human_reviews_ref", "reviews/human_reviews.json"), {}).get("reviews", [])
    return checkpoints, reviews
