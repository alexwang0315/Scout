"""Read-only evidence adapter for the opt-in Route Context field atlas."""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

from geo_utils import haversine_m


LAYER_LABELS = {
    "historical-jm20k-1904": ("1904", "臺灣堡圖"),
    "historical-fandi-1916": ("1916", "蕃地地形圖"),
    "historical-jm50k-1924": ("1924", "日治地形圖"),
    "historical-tm50k-1956": ("1956", "五萬分之一地形圖"),
    "historical-water-1966": ("1966", "水利地形圖"),
    "historical-economic-2001": ("2001", "經建版地形圖"),
    "imagery": (None, "NLSC 正射影像"),
}


def safe_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    return value


def finite_number(value: object) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


class RouteContextWorkspace:
    """Only curated fields and allowlisted raster paths can leave this adapter."""

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        self._receipts: dict[str, dict] = {}
        project = self.read_json("project.json")
        self.project_id = project.get("project_id", self.root.name)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.project_id):
            raise ValueError("Unsupported project identifier")
        self.evidence = self.read_json("inputs/route_context_regeneration_evidence.json")
        if self.evidence.get("project_id") != self.project_id:
            raise ValueError("Route context belongs to another project")
        self.summary = self.read_json("normalized/routes/route_summary.json")
        self.point_pack = self.read_json("candidates/route_context_points.json")
        if self.point_pack.get("project_id") != self.project_id:
            raise ValueError("Context points belong to another project")
        self.layers = self._layers()
        self.route = self._route()

    def path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Path is outside the selected workspace")
        return path

    def read_json(self, relative: str) -> dict:
        body = self.path(relative).read_bytes()
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("Expected an evidence object")
        self._receipts[relative] = {"source_ref": relative, "sha256": hashlib.sha256(body).hexdigest()}
        return value

    def receipt(self, relative: str) -> dict:
        if relative in self._receipts:
            return dict(self._receipts[relative])
        body = self.path(relative).read_bytes()
        return {"source_ref": relative, "sha256": hashlib.sha256(body).hexdigest()}

    def _layers(self) -> list[dict]:
        result = []
        for layer, (year, title) in LAYER_LABELS.items():
            relative = f"outputs/layers/manifests/{self.project_id}.{layer}.raster_tile_cache_manifest.json"
            if not self.path(relative).is_file():
                continue
            manifest = self.read_json(relative)
            if manifest.get("project_id") != self.project_id or manifest.get("layer_id") != layer:
                raise ValueError("Tile manifest binding mismatch")
            plan = manifest.get("plan", {})
            seed = manifest.get("seed_summary", {})
            bounds = plan.get("bbox_wgs84", {})
            root = self.path(f"cache/raster-tiles/{self.project_id}/{layer}")
            zooms = sorted(int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit()) if root.is_dir() else []
            if not zooms:
                continue
            result.append({
                "id": layer, "year": year, "title": title,
                "minzoom": min(zooms), "maxzoom": max(zooms),
                "bounds": [bounds[k] for k in ("west", "south", "east", "north")],
                "attribution": plan.get("source_attribution", "來源未記錄"),
                "source_id": manifest.get("imagery_source_id"),
                "cached_at": manifest.get("generated_at"),
                "acquired_at": None,
                "coverage_status": seed.get("status", "unknown"),
                "no_coverage_tiles": seed.get("tiles_no_coverage_total", 0),
                "tile_url": f"/tiles/{layer}/{{z}}/{{x}}/{{y}}.png",
                **self.receipt(relative),
            })
        return result

    def _route(self) -> dict:
        directory = self.path("normalized/routes/filtered")
        paths = sorted(directory.glob("primary.*.gpx"))
        if len(paths) != 1:
            raise ValueError("Expected exactly one bound primary GPX")
        relative = paths[0].relative_to(self.root).as_posix()
        body = self.path(relative).read_bytes()
        self._receipts[relative] = {"source_ref": relative, "sha256": hashlib.sha256(body).hexdigest()}
        if b"<!DOCTYPE" in body or b"<!ENTITY" in body:
            raise ValueError("GPX entity declarations are not accepted")
        root = ET.fromstring(body)
        segments, profile, times = [], [], []
        distance = 0.0
        for segment in root.findall(".//{*}trkseg"):
            coordinates, previous = [], None
            for point in segment.findall("{*}trkpt"):
                lat, lon = finite_number(point.get("lat")), finite_number(point.get("lon"))
                if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError("Invalid GPX position")
                elevation = finite_number(point.findtext("{*}ele"))
                if previous is not None:
                    distance += haversine_m(previous[1], previous[0], lat, lon)
                previous = [lon, lat]
                coordinates.append(previous)
                profile.append([round(distance, 2), elevation, lon, lat, len(segments)])
                time = point.findtext("{*}time")
                if time:
                    times.append(time)
            if len(coordinates) >= 2:
                segments.append(coordinates)
        if not segments:
            raise ValueError("No usable primary GPX track")
        all_coords = [p for segment in segments for p in segment]
        elevations = [p[1] for p in profile if p[1] is not None]
        return {
            "type": "Feature", "properties": {"kind": "recorded_gpx", "candidate_only": True},
            "geometry": {"type": "MultiLineString", "coordinates": segments},
            "profile": profile,
            "distance_m": round(distance, 2), "point_count": len(profile),
            "elevation_min_m": min(elevations) if elevations else None,
            "elevation_max_m": max(elevations) if elevations else None,
            "started_at": times[0] if times else None, "ended_at": times[-1] if times else None,
            "bounds": [min(p[0] for p in all_coords), min(p[1] for p in all_coords),
                       max(p[0] for p in all_coords), max(p[1] for p in all_coords)],
            **self.receipt(relative),
        }

    def points(self) -> list[dict]:
        result = []
        for point in self.point_pack.get("points", []):
            if point.get("evidence_type") != "major_critical_point":
                continue
            policy = point.get("display_policy", {})
            if not policy.get("show_label", False):
                continue
            allowed = (point.get("sensitivity_level") == "public"
                       and policy.get("show_exact_coordinate") is True
                       and policy.get("requires_human_review_before_display") is False)
            item = {
                "id": point["candidate_id"], "label": point.get("display_label", point.get("label", "")),
                "aliases": point.get("aliases", []), "position_allowed": allowed,
                "review_state": point.get("review_state", "unknown"),
                "source_tier": point.get("source_tier", "unknown"),
                "source_ref": "candidates/route_context_points.json", "candidate_only": True,
            }
            # Restricted locations never include coordinates, chainage or linked IDs.
            if allowed:
                lon, lat = finite_number(point.get("lon")), finite_number(point.get("lat"))
                if lon is not None and lat is not None and -180 <= lon <= 180 and -90 <= lat <= 90:
                    item["coordinates"] = [lon, lat]
                else:
                    item["position_allowed"] = False
            result.append(item)
        return result

    def catalog(self) -> dict:
        source_fields = ("source_id", "tier", "title", "published_at", "checked_at")
        sources = [{**{k: s.get(k) for k in source_fields}, "url": safe_url(s.get("url"))}
                   for s in self.evidence.get("sources", [])]
        claims = [{k: claim.get(k) for k in ("source_ids", "layer", "title", "text")}
                  for claim in self.evidence.get("context_claims", [])]
        status = self.evidence.get("current_status", {})
        gee_ref = "outputs/environment/gee/scout_gee_feature_package.json"
        gee = self.read_json(gee_ref) if self.path(gee_ref).is_file() else {}
        if gee and gee.get("project_id") != self.project_id:
            raise ValueError("GEE evidence belongs to another project")
        return {
            "schema_version": "route_context_demo.v1", "project_id": self.project_id,
            "display_name": self.evidence.get("display_name", self.project_id),
            "route_name": self.summary.get("route_name"), "checked_at": self.evidence.get("checked_at"),
            "identity": {k: self.evidence.get("route_identity", {}).get(k)
                         for k in ("direction", "explanation", "source_ids")},
            "status_snapshot": {"operability": status.get("operability", "unknown"),
                                "label": status.get("label"), "source_ids": status.get("source_ids", []),
                                "rechecked_in_demo": False},
            "route": self.route, "layers": self.layers, "points": self.points(),
            "claims": claims, "sources": sources,
            "research": {"gee_status": gee.get("status", "absent"),
                         "raw_feature_count": gee.get("counts", {}).get("raw_segment_feature_count", 0),
                         "external_api_calls_made": gee.get("boundary", {}).get("external_api_calls_made", False),
                         "blocker_reasons": gee.get("blocker_reasons", []),
                         "paired_spectral_dataset": None, "independent_labels": None,
                         "trained_model": None, "evaluation": None,
                         "source_ref": gee_ref if gee else None},
            "provenance": [self.receipt("inputs/route_context_regeneration_evidence.json"),
                           self.receipt("candidates/route_context_points.json"),
                           self.receipt("normalized/routes/route_summary.json")],
            "boundary": {"candidate_only": True, "runtime_safety_truth": False,
                         "workspace_writes": False, "model_inference_executed": False,
                         "remote_tile_fetch": False},
        }

    def tile(self, layer: str, z: int, x: int, y: int) -> Path:
        allowed = next((item for item in self.layers if item["id"] == layer), None)
        if not allowed or not (allowed["minzoom"] <= z <= allowed["maxzoom"] <= 24):
            raise ValueError("Unknown layer or zoom")
        if not (0 <= x < 2**z and 0 <= y < 2**z):
            raise ValueError("Invalid tile coordinate")
        path = self.path(f"cache/raster-tiles/{self.project_id}/{layer}/{z}/{x}/{y}.png")
        if not path.is_file():
            raise FileNotFoundError("Tile is not present in the selected workspace")
        return path
