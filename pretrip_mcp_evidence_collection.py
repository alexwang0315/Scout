"""Compile source-bound GPX, OSM and fetched-text evidence for MCP synthesis.

This module performs no network requests and changes no project metadata. The
default call is read-only; preparation explicitly requests artifact writes and
then publishes the returned refs before its dependent alignment/projections.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from geo_utils import haversine_m
from pretrip_mcp_models import (
    McpCandidateSet, McpClass, McpCpSupportReconciliation, McpPolicy,
    NamedPoint, NamedPointCollectedEvidenceProfile, NamedPointEvidencePage,
    NamedPointEvidenceSet, NamedPointRoutePosition,
)
from pretrip_mcp_synthesis import (
    build_cp_support_reconciliation, synthesize_mcp_candidates,
)


COLLECTOR_VERSION = "pretrip_mcp_evidence_collection.v1"
OUTPUT_REFS = {
    "mcp_named_point_evidence_ref": "outputs/mcp/named_point_evidence.json",
    "mcp_candidates_ref": "outputs/mcp/mcp_candidates.json",
    "mcp_cp_support_reconciliation_ref": "outputs/mcp/mcp_cp_support_reconciliation.json",
    "mcp_evidence_collection_receipt_ref": "outputs/mcp/mcp_evidence_collection_receipt.json",
}
PUBLIC_FAMILIES = {"ptt_hiking", "hiking_biji", "sunriver_culture", "public_web"}


class PublicMention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    aliases: list[str] = Field(default_factory=list)
    evidence_text: str
    source_locator: str | None = None
    coordinates_supplied: Literal[False] = False


class PublicDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    source_family: Literal["ptt_hiking", "hiking_biji", "sunriver_culture", "public_web"]
    url: str
    canonical_url: str
    title: str
    retrieved_at: str
    content_ref: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_relevance: Literal["low", "medium", "high"]
    accepted_for_route: bool
    route_match_reason: str
    stale_risk: Literal["low", "medium", "high"]
    mentions: list[PublicMention]
    dependent_source_sha256: list[str] = Field(default_factory=list)
    observation_group: str | None = None
    original_document: str | dict[str, str] | None = None
    published_at: str | None = None
    publisher: str | None = None
    author_or_publisher: str | None = None
    document_period: str | None = None
    independent_document_id: str | None = None
    raw_content_ref: str | None = None
    raw_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    fetch_receipt_ref: str | None = None
    evidence_role: str | None = None
    full_payload_embedded: Literal[False] = False


class PublicAcquisitionAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_family: Literal["ptt_hiking", "hiking_biji", "sunriver_culture", "public_web"]
    query_or_url: str
    attempted_at: str
    outcome: str
    receipt_ref: str
    receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    network_performed: bool = False


class PublicAcquisition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempted_source_families: list[str]
    attempts: list[PublicAcquisitionAttempt]
    discovery_receipt_refs: list[str] = Field(default_factory=list)
    source_fetch_policy: str | None = None


class PublicSourceBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    auto_accept_permission: Literal[False] = False
    coordinates_invented: Literal[False] = False


class McpPublicSourceRecords(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_kind: Literal["pretrip_mcp_public_source_records"]
    project_id: str
    acquisition: PublicAcquisition
    documents: list[PublicDocument]
    schema_version: str = "mcp_public_source_records.v1"
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    binding: Literal["project_id", "golden_source_sha256"] = "project_id"
    golden_source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    generated_at: str | None = None
    live_network_performed: bool = False
    fixture_backed: Literal[False] = False
    boundary: PublicSourceBoundary = Field(default_factory=PublicSourceBoundary)
    qualification_notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class McpEvidenceCollectionResult:
    status: str
    evidence_set: NamedPointEvidenceSet | None
    candidate_set: McpCandidateSet | None
    cp_support: McpCpSupportReconciliation | None
    receipt: dict[str, Any]
    output_refs: dict[str, str]
    counts: dict[str, int]

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status, "outputs": self.output_refs,
            "counts": self.counts, "gaps": self.receipt.get("gaps", []),
            "source_bindings": self.receipt.get("source_bindings", []),
            "candidate_only": True, "runtime_safety_truth": False,
        }


@dataclass(frozen=True)
class _Observation:
    page_id: str
    record_id: str
    name: str
    aliases: tuple[str, ...]
    classes: tuple[McpClass, ...]
    lat: float
    lon: float
    progress_m: float
    offset_m: float
    coordinate_confidence: str = "medium"


@dataclass
class _Cluster:
    observations: list[_Observation] = field(default_factory=list)
    web_mentions: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def keys(self) -> set[str]:
        return {
            _name_key(name)
            for observation in self.observations
            for name in (observation.name, *observation.aliases)
        }


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _bound_path(root: Path, ref: str) -> Path:
    if not ref or Path(ref).is_absolute():
        raise ValueError("source ref must be a relative path")
    if any(part == ".git" or part == ".env" or part.startswith(".env.") for part in Path(ref).parts):
        raise ValueError("credential and Git files are not source documents")
    resolved = (root / ref).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("source ref escapes its declared root")
    if not resolved.is_file():
        raise ValueError("source file is missing")
    return resolved


def _binding(path: Path, *, role: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {"source_ref": str(path.resolve()), "sha256": _sha(data),
            "size_bytes": len(data), "role": role}


def discover_mcp_supplemental_evidence(material_root: Path | str | None) -> Path | None:
    if material_root is None:
        return None
    root = Path(material_root).resolve()
    manifest = root / "material_manifest.json"
    if manifest.is_file():
        source = json.loads(manifest.read_text()).get("sources", {}).get("mcp", {})
        if isinstance(source, dict) and source.get("supplemental_evidence_ref"):
            return _bound_path(root, source["supplemental_evidence_ref"])
    default = "sources/mcp/public_source_evidence.json"
    return _bound_path(root, default) if (root / default).is_file() else None


def mcp_supplemental_source_bindings(path: Path | str) -> list[dict[str, Any]]:
    package_path = Path(path).resolve()
    package = McpPublicSourceRecords.model_validate_json(package_path.read_text())
    bindings = [_binding(package_path, role="mcp_public_source_package")]
    for document in package.documents:
        item = _binding(_bound_path(package_path.parent, document.content_ref), role="mcp_public_source_text")
        if item["sha256"] != document.content_sha256:
            raise ValueError("public source content hash mismatch")
        bindings.append(item)
        if document.raw_content_ref:
            item = _binding(_bound_path(package_path.parent, document.raw_content_ref), role="mcp_public_raw_source")
            if not document.raw_content_sha256 or item["sha256"] != document.raw_content_sha256:
                raise ValueError("public raw source hash mismatch")
            bindings.append(item)
        if document.fetch_receipt_ref:
            bindings.append(_binding(_bound_path(package_path.parent, document.fetch_receipt_ref), role="mcp_public_fetch_receipt"))
    for attempt in package.acquisition.attempts:
        item = _binding(_bound_path(package_path.parent, attempt.receipt_ref), role="mcp_public_acquisition_receipt")
        if attempt.receipt_sha256 and item["sha256"] != attempt.receipt_sha256:
            raise ValueError("public acquisition receipt hash mismatch")
        bindings.append(item)
    for ref in package.acquisition.discovery_receipt_refs:
        bindings.append(_binding(_bound_path(package_path.parent, ref), role="mcp_public_discovery_receipt"))
    return list({item["source_ref"]: item for item in bindings}.values())


def _xml(data: bytes) -> ET.Element:
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("GPX document declarations and entities are not permitted")
    return ET.fromstring(data)


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _text(element: ET.Element, tag: str) -> str:
    return next((child.text or "" for child in element if _tag(child) == tag), "").strip()


def _coordinate(element: ET.Element) -> tuple[float, float] | None:
    try:
        lat, lon = float(element.attrib["lat"]), float(element.attrib["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    return (lat, lon) if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180 else None


def _name_key(value: str) -> str:
    name = unicodedata.normalize("NFKC", value).strip()
    name = re.sub(r"^\d{3,4}[\s._-]*[a-z]?[\s._-]*", "", name)
    return re.sub(r"\s+", "", name).casefold()


def _classes(name: str, tags: dict[str, Any] | None = None) -> tuple[McpClass, ...]:
    text = _name_key(name)
    result: list[McpClass] = []
    rules: tuple[tuple[McpClass, str], ...] = (
        ("fork_junction", r"岔|叉路|交會|交叉|junction|fork"),
        ("camp_hut_structure", r"營地|山莊|山屋|工寮|獵寮|保線所|駐在所|避難|遺址|camp|hut|shelter"),
        # A named pool is a water-related planning decision point. Its label
        # never establishes present water availability or drinkability.
        ("water_source", r"水源|活水|取水|溪水|湧泉|飲水|水池|池$|water.?source|spring"),
        ("extreme_terrain_hazard", r"崩壁|崩塌|斷崖|岩壁|落石|碎石坡|險坡|cliff|landslide"),
        ("hidden_forest_route_loss", r"迷途|迷路|路跡不明|路徑不明|密林|芒草|箭竹|route.?loss"),
        ("viewpoint_trailhead_pass", r"登山口|鞍部|鞍$|觀景|展望|瀑布|山頂|峰|山$|pass$|peak$|viewpoint|trailhead"),
        ("technical_infrastructure", r"吊橋|木橋|鐵橋|石橋|隧道|拉繩|繩梯|鐵梯|渡溪|bridge|tunnel|ladder"),
        ("mobile_reception", r"收訊|通訊點|通信點|訊號|reception"),
    )
    for point_class, pattern in rules:
        if re.search(pattern, text, re.I):
            result.append(point_class)
    tags = tags or {}
    tag_rules: dict[McpClass, bool] = {
        "camp_hut_structure": tags.get("tourism") in {"camp_site", "alpine_hut", "wilderness_hut"} or tags.get("amenity") == "shelter",
        "water_source": tags.get("natural") == "spring" or tags.get("amenity") == "drinking_water",
        "viewpoint_trailhead_pass": tags.get("natural") in {"peak", "saddle"} or tags.get("tourism") == "viewpoint" or tags.get("highway") == "trailhead",
        "technical_infrastructure": tags.get("bridge") == "yes" or tags.get("tunnel") == "yes",
        "extreme_terrain_hazard": tags.get("natural") == "cliff" or tags.get("geological") == "landslide",
    }
    return tuple(dict.fromkeys([*result, *(kind for kind, matches in tag_rules.items() if matches)]))


class _RouteAxis:
    """Indexed segment projections; GPX segment gaps never become new trails."""
    def __init__(self, document: ET.Element, corridor_m: float):
        self.corridor_m = corridor_m
        groups = [element for element in document.iter() if _tag(element) in {"trkseg", "rte"}]
        all_points = [point for group in groups for element in group if (point := _coordinate(element)) is not None]
        if len(all_points) < 2:
            raise ValueError("Golden GPX has no route geometry")
        self.lat0, self.lon0 = all_points[0]
        self.lon_scale = 111_195.08 * math.cos(math.radians(self.lat0))
        self.cell_m = max(50.0, corridor_m)
        self.edges: list[tuple[float, float, float, float, float, float]] = []
        self.grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        self.gap_edge_count = 0
        progress = 0.0
        for group in groups:
            previous = None
            for element in group:
                current = _coordinate(element)
                if current is None:
                    previous = None
                    continue
                if previous is not None:
                    length = haversine_m(*previous, *current)
                    if 0 < length <= 2000:
                        ax, ay = self.xy(*previous)
                        bx, by = self.xy(*current)
                        index = len(self.edges)
                        self.edges.append((ax, ay, bx, by, progress, length))
                        padding = corridor_m * 1.02
                        for x in range(math.floor((min(ax, bx) - padding) / self.cell_m), math.floor((max(ax, bx) + padding) / self.cell_m) + 1):
                            for y in range(math.floor((min(ay, by) - padding) / self.cell_m), math.floor((max(ay, by) + padding) / self.cell_m) + 1):
                                self.grid[x, y].append(index)
                    elif length > 2000:
                        self.gap_edge_count += 1
                    progress += length
                previous = current
        self.distance_m = progress
        if not self.edges:
            raise ValueError("Golden GPX has no continuous route edges")

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.lon_scale, (lat - self.lat0) * 111_195.08

    def project(self, lat: float, lon: float) -> tuple[float, float] | None:
        x, y = self.xy(lat, lon)
        closest = None
        for index in self.grid.get((math.floor(x / self.cell_m), math.floor(y / self.cell_m)), ()):
            ax, ay, bx, by, start, length = self.edges[index]
            dx, dy = bx - ax, by - ay
            squared = dx * dx + dy * dy
            t = min(1.0, max(0.0, ((x - ax) * dx + (y - ay) * dy) / squared))
            projected_lat = self.lat0 + (ay + t * dy) / 111_195.08
            projected_lon = self.lon0 + (ax + t * dx) / self.lon_scale
            offset = haversine_m(lat, lon, projected_lat, projected_lon)
            pair = (offset, start + t * length)
            if offset <= self.corridor_m and (closest is None or pair < closest):
                closest = pair
        return (closest[1], closest[0]) if closest else None


def _gpx_sources(root: Path, project: dict[str, Any], axis: _RouteAxis, receipt: dict[str, Any], generated_at: str) -> tuple[list[NamedPointEvidencePage], list[_Observation]]:
    index_ref = project.get("historical_gpx_source_index_ref", "sources/historical_gpx_source_index.json")
    index_path = _bound_path(root, index_ref)
    receipt["source_bindings"].append(_binding(index_path, role="gpx_source_index"))
    source_index = json.loads(index_path.read_text())
    if source_index.get("project_id") != project["project_id"]:
        raise ValueError("GPX source index belongs to a different project")
    pages, observations = [], []
    seen: dict[str, str] = {}
    for source in source_index.get("sources", []):
        ref = source.get("workspace_ref", "")
        source_receipt = {"source_ref": ref, "accepted": False}
        receipt["documents"].append(source_receipt)
        try:
            path = _bound_path(root, ref)
            data = path.read_bytes()
            actual_hash = _sha(data)
            receipt["source_bindings"].append({"source_ref": str(path), "sha256": actual_hash, "size_bytes": len(data), "role": "gpx_raw_document"})
            if actual_hash != source.get("sha256"):
                raise ValueError("raw GPX hash mismatch")
            document = _xml(data)
        except (ValueError, ET.ParseError) as error:
            source_receipt["reason"] = str(error)
            continue
        records = [(element, _coordinate(element)) for element in document.iter() if _tag(element) in {"wpt", "trkpt", "rtept"}]
        semantic_hash = _sha(_json_bytes([(_tag(element), coordinate, _text(element, "time"), _text(element, "name"), _text(element, "cmt"), _text(element, "desc")) for element, coordinate in records]))
        page_id = f"gpx.{actual_hash}"
        source_receipt.update(page_id=page_id, sha256=actual_hash, semantic_sha256=semantic_hash)
        if actual_hash in seen or semantic_hash in seen:
            source_receipt.update(reason="duplicate_gpx_document", duplicate_of=seen.get(actual_hash, seen.get(semantic_hash)))
            continue
        seen[actual_hash] = seen[semantic_hash] = page_id
        local: list[_Observation] = []
        relevant_track_points: set[tuple[float, float]] = set()
        track_count = 0
        for index, (element, coordinate) in enumerate(records):
            if coordinate is None:
                continue
            if _tag(element) != "wpt":
                track_count += 1
                if len(relevant_track_points) < 3 and axis.project(*coordinate) is not None:
                    relevant_track_points.add(coordinate)
            name = _text(element, "name")
            if not name:
                continue
            record_id = f"{_tag(element)}.{index}"
            classes = _classes(name)
            projection = axis.project(*coordinate) if classes else None
            if not classes or projection is None:
                receipt["rejected_records"].append({"page_id": page_id, "record_id": record_id, "reason": "unsupported_named_point_class" if not classes else "outside_golden_route_corridor"})
                continue
            local.append(_Observation(page_id, record_id, name, (), classes, *coordinate, *projection))
        accepted = bool(local) and (track_count == 0 or len(relevant_track_points) >= 3)
        reason = "source_bound_named_points_with_route_geometry_overlap" if accepted else ("route_track_outside_golden_corridor" if local else "no_route_significant_named_points_in_corridor")
        source_receipt.update(accepted=accepted, reason=reason, named_point_record_count=len(local), route_track_overlap_observed=len(relevant_track_points) >= 3)
        pages.append(NamedPointEvidencePage(
            page_id=page_id, source_family="reference_gpx", url=path.as_uri(),
            title=source.get("original_filename", path.name), retrieved_at=source.get("imported_at") or generated_at,
            accepted=accepted, route_relevance="high" if accepted else "low", stale_risk="high",
            snippet_hash=actual_hash, evidence_kind="gpx_document", source_ref=ref,
            source_sha256=actual_hash, source_record_ids=tuple(item.record_id for item in local),
            independent_document_id=f"gpx-document.{semantic_hash}", acceptance_reason=reason,
        ))
        if accepted:
            observations.extend(local)
    return pages, observations


def _osm_sources(root: Path, project: dict[str, Any], axis: _RouteAxis, receipt: dict[str, Any], generated_at: str) -> tuple[list[NamedPointEvidencePage], list[_Observation]]:
    ref = project.get("overpass_evidence_ref")
    raw_ref = project.get("overpass_raw_payload_ref") or project.get("osm_pbf_raw_payload_ref")
    if not ref or not raw_ref:
        receipt["gaps"].append("OSM raw payload or normalized evidence is missing")
        return [], []
    evidence_path, raw_path = _bound_path(root, ref), _bound_path(root, raw_ref)
    raw = raw_path.read_bytes()
    raw_hash = _sha(raw)
    evidence = json.loads(evidence_path.read_text())
    receipt["source_bindings"].extend([_binding(evidence_path, role="osm_normalized_evidence"), _binding(raw_path, role="osm_raw_document")])
    raw_payload = json.loads(raw)
    declared_hash = evidence.get("source_artifact", {}).get("sha256")
    canonical_hash = _sha(json.dumps(raw_payload, ensure_ascii=False, sort_keys=True).encode())
    # The existing OSM normalizers hash sorted JSON before the pretty-printed
    # file is persisted. Bind both its declared payload digest and actual bytes.
    if not declared_hash or declared_hash not in {raw_hash, canonical_hash}:
        receipt["gaps"].append("OSM raw payload hash mismatch")
        return [], []
    receipt["osm_payload_binding"] = {"declared_payload_sha256": declared_hash, "file_sha256": raw_hash, "canonical_payload_sha256": canonical_hash}
    raw_objects = {(str(item.get("type")), str(item.get("id"))): item for item in raw_payload.get("elements", [])}
    page_id = f"osm.{raw_hash}"
    observations, seen = [], set()
    for record in evidence.get("object_evidence", []):
        key = str(record.get("osm_type")), str(record.get("osm_id"))
        record_id = "/".join(key)
        if key in seen:
            continue
        seen.add(key)
        actual = raw_objects.get(key)
        tags = (actual or {}).get("tags", {})
        name = str(tags.get("name") or tags.get("name:zh") or "").strip()
        geometry = record.get("geometry") or {}
        classes = _classes(name, tags) if name else ()
        reason = None
        if actual is None or tags != record.get("tags", {}):
            reason = "osm_record_not_bound_to_raw_tags"
        elif geometry.get("type") != "Point" or key[0] != "node":
            reason = "osm_nonpoint_feature_requires_explicit_location_review"
        elif not classes:
            reason = "unsupported_named_point_class"
        if reason:
            receipt["rejected_records"].append({"page_id": page_id, "record_id": record_id, "reason": reason})
            continue
        try:
            lat, lon = float(actual["lat"]), float(actual["lon"])
            coordinates = geometry["coordinates"]
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or abs(coordinates[0] - lon) > 1e-7 or abs(coordinates[1] - lat) > 1e-7:
                raise ValueError("coordinate mismatch")
        except (KeyError, TypeError, ValueError, IndexError):
            receipt["rejected_records"].append({"page_id": page_id, "record_id": record_id, "reason": "osm_coordinate_not_bound_to_raw_node"})
            continue
        projection = axis.project(lat, lon)
        if projection is None:
            receipt["rejected_records"].append({"page_id": page_id, "record_id": record_id, "reason": "outside_golden_route_corridor"})
            continue
        aliases = tuple(dict.fromkeys(str(value).strip() for field_name in ("alt_name", "name:zh", "name:en") for value in str(tags.get(field_name, "")).split(";") if str(value).strip()))
        observations.append(_Observation(page_id, record_id, name, aliases, classes, lat, lon, *projection, "high"))
    accepted = bool(observations)
    reason = "one_osm_snapshot_with_source_verified_route_named_nodes" if accepted else "no_source_verified_named_osm_nodes_in_route_corridor"
    page = NamedPointEvidencePage(page_id=page_id, source_family="openstreetmap", url=raw_path.as_uri(), title="Route OSM snapshot", retrieved_at=generated_at,
        accepted=accepted, route_relevance="high" if accepted else "low", stale_risk="medium", snippet_hash=raw_hash,
        evidence_kind="osm_snapshot", source_ref=raw_ref, source_sha256=raw_hash,
        independent_document_id="openstreetmap.snapshot", source_record_ids=tuple(item.record_id for item in observations), acceptance_reason=reason)
    receipt["documents"].append({"page_id": page_id, "source_ref": raw_ref, "accepted": accepted, "reason": reason, "named_point_record_count": len(observations)})
    return [page], observations


def _cluster(observations: list[_Observation]) -> list[_Cluster]:
    clusters: list[_Cluster] = []
    for observation in sorted(observations, key=lambda item: (_name_key(item.name), item.lat, item.lon, item.page_id, item.record_id)):
        keys = {_name_key(name) for name in (observation.name, *observation.aliases)}
        target = next((item for item in clusters if keys & item.keys and all(haversine_m(observation.lat, observation.lon, other.lat, other.lon) <= 100 for other in item.observations)), None)
        if target is None:
            target = _Cluster()
            clusters.append(target)
        target.observations.append(observation)
    return clusters


def _canonical_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("public document requires a public HTTP URL without credentials")
    query = sorted((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"})
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ""))


def _add_public_sources(path: Path, project_id: str, golden_source_sha256: str | None, clusters: list[_Cluster], pages: list[NamedPointEvidencePage], receipt: dict[str, Any]) -> set[str]:
    package = McpPublicSourceRecords.model_validate_json(path.read_text())
    if package.binding == "golden_source_sha256":
        if not package.golden_source_sha256 or package.golden_source_sha256 != golden_source_sha256:
            raise ValueError("supplemental MCP evidence Golden source hash mismatch")
    elif package.project_id != project_id:
        raise ValueError("supplemental MCP evidence belongs to a different project")
    receipt["supplemental_binding"] = {"binding": package.binding, "source_project_id": package.project_id,
        "target_project_id": project_id, "golden_source_sha256": package.golden_source_sha256,
        "review_or_acceptance_reused": False}
    receipt["source_bindings"].extend(mcp_supplemental_source_bindings(path))
    attempts = {attempt.source_family for attempt in package.acquisition.attempts if attempt.query_or_url.strip() and attempt.attempted_at.strip() and attempt.outcome.strip()}
    if set(package.acquisition.attempted_source_families) != attempts:
        raise ValueError("public source attempts must match their actual acquisition receipts")
    receipt["public_acquisition_attempts"] = [attempt.model_dump() for attempt in package.acquisition.attempts]
    seen_urls, seen_content, seen_groups = {}, {}, {}
    accepted_source_hashes = {page.source_sha256 for page in pages if page.accepted}
    for document in package.documents:
        content_path = _bound_path(path.parent, document.content_ref)
        content = content_path.read_text()
        canonical_url = _canonical_url(document.canonical_url)
        page_id = f"web.{_sha(canonical_url.encode())}"
        accepted = document.accepted_for_route and document.route_relevance != "low" and bool(document.route_match_reason.strip())
        reason = document.route_match_reason
        dependent = set(document.dependent_source_sha256) & accepted_source_hashes
        duplicate = canonical_url in seen_urls or document.content_sha256 in seen_content or (document.observation_group and document.observation_group in seen_groups)
        if dependent or duplicate:
            accepted, reason = False, "dependent_or_duplicate_document_not_an_independent_source"
        local_mentions = []
        for index, mention in enumerate(document.mentions):
            mention_ref = f"mention.{index}"
            keys = {_name_key(name) for name in (mention.name, *mention.aliases) if _name_key(name) in _name_key(mention.evidence_text)}
            matches = [item for item in clusters if keys & item.keys]
            if not mention.evidence_text or mention.evidence_text not in content or not any(_name_key(name) in _name_key(mention.evidence_text) for name in (mention.name, *mention.aliases)):
                rejection = "mention_not_present_in_saved_source_text"
            elif len(matches) != 1:
                rejection = "named_point_location_missing_or_ambiguous"
            else:
                rejection = None
            if rejection:
                receipt["rejected_records"].append({"page_id": page_id, "record_id": mention_ref, "reason": rejection})
                continue
            local_mentions.append((matches[0], mention_ref, mention.name))
        if accepted and not local_mentions:
            accepted, reason = False, "no_source_text_mentions_with_unambiguous_route_position"
        # Distinct copies of one canonical document are retained in the receipt,
        # not duplicated in the typed page catalog or mention denominator.
        if page_id in {page.page_id for page in pages}:
            receipt["documents"].append({"page_id": page_id, "document_id": document.document_id, "accepted": False, "reason": "duplicate_canonical_url"})
            continue
        independent = f"web-document.{document.content_sha256}"
        pages.append(NamedPointEvidencePage(page_id=page_id, source_family=document.source_family,
            url=document.url, canonical_url=canonical_url, title=document.title, retrieved_at=document.retrieved_at,
            accepted=accepted, route_relevance=document.route_relevance, stale_risk=document.stale_risk,
            snippet_hash=document.content_sha256, source_ref=str(content_path), source_sha256=document.content_sha256,
            source_record_ids=tuple(item[1] for item in local_mentions), independent_document_id=independent, acceptance_reason=reason))
        if accepted:
            seen_urls[canonical_url] = seen_content[document.content_sha256] = page_id
            if document.observation_group:
                seen_groups[document.observation_group] = page_id
        for cluster, mention_ref, name in local_mentions:
            if accepted or dependent:
                cluster.web_mentions.append((page_id, mention_ref, name))
        receipt["documents"].append({"page_id": page_id, "document_id": document.document_id, "accepted": accepted, "reason": reason, "dependent_source_sha256": sorted(dependent), "named_point_record_count": len(local_mentions)})
    return attempts


def collect_mcp_evidence(project_root: Path | str, *, route_corridor_m: float = 500.0,
    supplemental_evidence_path: Path | str | None = None, output_root: Path | str | None = None,
    write_outputs: bool = False, generated_at: str | None = None) -> McpEvidenceCollectionResult:
    if not math.isfinite(route_corridor_m) or route_corridor_m <= 0:
        raise ValueError("route_corridor_m must be positive and finite")
    root = Path(project_root).resolve()
    project_path = _bound_path(root, "project.json")
    project = json.loads(project_path.read_text())
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    policy = McpPolicy()
    receipt: dict[str, Any] = {
        "artifact_kind": "pretrip_mcp_evidence_collection_receipt", "schema_version": COLLECTOR_VERSION,
        "project_id": project["project_id"], "generated_at": generated_at,
        "candidate_only": True, "runtime_safety_truth": False, "human_review_required": True,
        "fixture_backed": False, "network_requests_made": 0, "model_requests_made": 0,
        "source_bindings": [], "documents": [], "rejected_records": [], "gaps": [],
        "policy": policy.model_dump(mode="json"), "policy_thresholds_changed": False,
        "corridor_policy": {"route_corridor_m": route_corridor_m, "basis": "selected_golden_filtered_gpx", "entity_merge_diameter_m": 100, "route_gap_max_edge_m": 2000},
    }
    bundle_path = _bound_path(root, project.get("route_evidence_bundle_ref", "normalized/routes/route_evidence_bundle.json"))
    bundle = json.loads(bundle_path.read_text())
    if bundle.get("project_id") != project["project_id"]:
        raise ValueError("Golden route bundle belongs to a different project")
    golden = bundle.get("golden_route", {})
    route_path = _bound_path(root, golden.get("filtered_geometry_ref", ""))
    route_data = route_path.read_bytes()
    route_hash = _sha(route_data)
    if golden.get("filtered_geometry_sha256") != route_hash:
        raise ValueError("Golden filtered route hash mismatch")
    receipt["source_bindings"].extend([_binding(bundle_path, role="golden_route_bundle"), _binding(route_path, role="golden_filtered_route")])
    axis = _RouteAxis(_xml(route_data), route_corridor_m)
    receipt["route_binding"] = {"source_ref": golden["filtered_geometry_ref"], "sha256": route_hash, "source_gpx_sha256": golden.get("sha256"), "distance_m": axis.distance_m, "excluded_gap_edge_count": axis.gap_edge_count}
    pages, observations = _gpx_sources(root, project, axis, receipt, generated_at)
    attempted = {"reference_gpx"}
    osm_pages, osm_observations = _osm_sources(root, project, axis, receipt, generated_at)
    pages.extend(osm_pages)
    observations.extend(osm_observations)
    if osm_pages:
        attempted.add("openstreetmap")
    clusters = _cluster(observations)
    if supplemental_evidence_path is not None:
        attempted.update(_add_public_sources(Path(supplemental_evidence_path).resolve(), project["project_id"], golden.get("sha256"), clusters, pages, receipt))
    page_by_id = {page.page_id: page for page in pages}
    accepted_count = sum(page.accepted for page in pages)
    missing_attempts = tuple(family for family in policy.required_source_families if family not in attempted)
    named_points = []
    for cluster in clusters:
        representative = min(cluster.observations, key=lambda item: (item.coordinate_confidence != "high", item.offset_m, item.page_id, item.record_id))
        ids = tuple(sorted({item.page_id for item in cluster.observations} | {item[0] for item in cluster.web_mentions}))
        families = tuple(sorted({page_by_id[page_id].source_family for page_id in ids if page_by_id[page_id].accepted}))
        names = tuple(sorted({name for item in cluster.observations for name in (item.name, *item.aliases)} | {item[2] for item in cluster.web_mentions}))
        named_id = "np.local." + _sha(_json_bytes([_name_key(representative.name), round(representative.lat, 6), round(representative.lon, 6)]))[:20]
        named_points.append(NamedPoint(named_point_id=named_id, canonical_name=representative.name, aliases=names,
            point_class=tuple(sorted({kind for item in cluster.observations for kind in item.classes})),
            mention_page_ids=ids, mention_page_count=len(ids), mention_ratio=sum(page_by_id[page_id].accepted for page_id in ids) / accepted_count if accepted_count else 0,
            source_families=families, missing_source_families=tuple(family for family in policy.required_source_families if family not in families),
            route_position=NamedPointRoutePosition(distance_m=round(representative.progress_m, 3), lat=representative.lat, lon=representative.lon, coordinate_confidence=representative.coordinate_confidence),
            route_corridor_offset_m=round(representative.offset_m, 3), stale_risk=max((page_by_id[page_id].stale_risk for page_id in ids), key={"low": 0, "medium": 1, "high": 2}.__getitem__),
            source_record_refs=tuple(sorted({f"{item.page_id}#{item.record_id}" for item in cluster.observations} | {f"{item[0]}#{item[1]}" for item in cluster.web_mentions}))))
    evidence = NamedPointEvidenceSet(project_id=project["project_id"], source_path=OUTPUT_REFS["mcp_named_point_evidence_ref"],
        search_profile=NamedPointCollectedEvidenceProfile(required_source_families=policy.required_source_families, attempted_source_families=tuple(sorted(attempted)),
            unattempted_required_source_families=missing_attempts, accepted_evidence_page_count=accepted_count,
            source_acquisition_network_performed=bool(receipt.get("public_acquisition_attempts"))),
        evidence_pages=tuple(pages), named_points=tuple(sorted(named_points, key=lambda item: (item.route_position.distance_m, item.named_point_id))))
    if project.get("checkpoint_candidates_ref"):
        checkpoint_path = _bound_path(root, project["checkpoint_candidates_ref"])
        receipt["source_bindings"].append(_binding(checkpoint_path, role="scout_checkpoint_support"))
    candidates = synthesize_mcp_candidates(evidence, project_root=root, policy=policy, source_refs=(OUTPUT_REFS["mcp_named_point_evidence_ref"], OUTPUT_REFS["mcp_evidence_collection_receipt_ref"]))
    # The shared scoring/spacing algorithm also serves fixture tests; annotate
    # this real invocation without falsely claiming that a model was called.
    candidates = candidates.model_copy(update={"mcp_candidates": tuple(candidate.model_copy(update={
        "pydantic_ai_prompt_version": "not_applicable_deterministic_source_collection.v1",
        "model_output_summary": "Deterministic MCP synthesis from hash-verified route source documents; no model request; candidate requires human review.",
    }) for candidate in candidates.mcp_candidates)})
    cp_support = build_cp_support_reconciliation(candidates, source_candidate_set_ref=OUTPUT_REFS["mcp_candidates_ref"])
    if accepted_count < policy.np_min_accepted_evidence_pages:
        receipt["gaps"].append(f"accepted independent source documents {accepted_count} < required {policy.np_min_accepted_evidence_pages}")
    if missing_attempts:
        receipt["gaps"].append("required public source families not attempted: " + ", ".join(missing_attempts))
    if not candidates.mcp_candidate_count:
        receipt["gaps"].append("no named points meet the unchanged MCP promotion policy")
    counts = {"mcp_candidate_count": candidates.mcp_candidate_count, "mcp_dense_checkpoint_count": candidates.dense_checkpoint_count,
        "mcp_suppressed_point_count": candidates.suppressed_point_count, "mcp_named_point_count": len(evidence.named_points),
        "mcp_accepted_evidence_document_count": accepted_count, "mcp_accepted_source_count": accepted_count, "mcp_cp_supported_count": cp_support.supported_count,
        "mcp_cp_suggested_insertion_count": cp_support.suggested_insertion_count}
    status = "insufficient_evidence" if receipt["gaps"] else "completed"
    receipt.update(status=status, counts=counts, evidence_sha256=_sha(evidence.to_json().encode()),
        candidates_sha256=_sha(candidates.to_json().encode()), rejected_reason_counts=dict(Counter(item["reason"] for item in receipt["rejected_records"])))
    if write_outputs:
        destination_root = Path(output_root).resolve() if output_root is not None else root
        if any(not (destination_root / ref).resolve().is_relative_to(destination_root) for ref in OUTPUT_REFS.values()):
            raise ValueError("MCP output path escapes its declared root")
        evidence_destination = destination_root / OUTPUT_REFS["mcp_named_point_evidence_ref"]
        if evidence_destination.is_file():
            previous = NamedPointEvidenceSet.model_validate_json(evidence_destination.read_text())
            if not isinstance(previous.search_profile, NamedPointCollectedEvidenceProfile):
                raise ValueError("existing explicitly supplied named-point evidence must be preserved")
        payloads = {"mcp_named_point_evidence_ref": evidence.to_json().encode(), "mcp_candidates_ref": candidates.to_json().encode(),
            "mcp_cp_support_reconciliation_ref": cp_support.to_json().encode(), "mcp_evidence_collection_receipt_ref": _json_bytes(receipt)}
        for key, data in payloads.items():
            destination = destination_root / OUTPUT_REFS[key]
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
    return McpEvidenceCollectionResult(status, evidence, candidates, cp_support, receipt, dict(OUTPUT_REFS), counts)
