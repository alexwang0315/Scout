"""Read-only, project-scoped inputs for the experimental GPX viewer.

No admin/runtime app is imported. No preparation, import, promotion, or network
fetch is performed. Prepared terrain uses the existing validated tile reader.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from navigation_terrain_raster_dem import (
    TerrainDemPreparationError,
    load_navigation_terrain_dem_manifest,
    navigation_terrain_dem_tile,
)
from qgis_spatial_contracts import SpatialAuthorityBoundary


class DisplayAuthority(SpatialAuthorityBoundary):
    """Add display scope to Scout's existing literal authority boundary."""

    visualization_only: Literal[True] = True
    workspace_file_mutation_allowed: Literal[False] = False


class SourceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_ref: str
    sha256: str
    size_bytes: int
    data_type: Literal["unknown"] = "unknown"
    data_type_basis: str = "GPX filename and timestamps do not establish source type"
    workspace_role: str = "unknown"
    identity_basis: str = "local bytes"


class DisplayCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scout_gpx_3d.v0"] = "scout_gpx_3d.v0"
    status: Literal["ready", "empty", "unavailable"]
    summary: str
    project_id: str
    sources: list[SourceIdentity] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    authority: DisplayAuthority = Field(default_factory=DisplayAuthority)
    preferred_source_id: str | None = None


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def local_ref(root: Path, ref: str) -> Path:
    path = (root / ref).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Source reference escapes the selected project")
    return path


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


class Gpx3DWorkspace:
    def __init__(self, project_root: Path):
        self.root = project_root.expanduser().resolve()

    def project(self) -> dict[str, Any]:
        path = local_ref(self.root, "project.json")
        if not path.is_file():
            return {"project_id": self.root.name}
        return read_object(path)

    def source_paths(self) -> dict[str, Path]:
        if not self.root.is_dir():
            return {}
        # Only the explicitly selected project is catalogued; never other trips.
        paths = sorted(self.root.rglob("*"))
        return {
            digest(path.relative_to(self.root).as_posix().encode())[:24]: path
            for path in paths
            if path.suffix.lower() == ".gpx"
            and path.is_file()
            and path.resolve().is_relative_to(self.root)
        }

    def source(self, source_id: str) -> tuple[SourceIdentity, bytes]:
        path = self.source_paths().get(source_id)
        if path is None:
            raise FileNotFoundError("GPX is not in the selected project")
        body = local_ref(self.root, path.relative_to(self.root).as_posix()).read_bytes()
        identity = SourceIdentity(
            id=source_id,
            source_ref=path.relative_to(self.root).as_posix(),
            sha256=digest(body),
            size_bytes=len(body),
        )
        project = self.project()
        ref = project.get("source_inbox_manifest_ref")
        if ref:
            manifest = read_object(local_ref(self.root, str(ref)))
            for item in manifest.get("sources", []):
                if item.get("workspace_ref") == identity.source_ref and item.get("sha256") == identity.sha256:
                    identity.workspace_role = str(item.get("role") or "unknown")
                    identity.identity_basis = f"sha256 verified against {ref}"
        return identity, body

    def catalog(self) -> DisplayCatalog:
        sources = [self.source(key)[0] for key in self.source_paths()]
        status = "ready" if sources else "empty" if self.root.is_dir() else "unavailable"
        return DisplayCatalog(
            status=status,
            summary={
                "ready": "請選擇此 Workspace 中要展示的 GPX。",
                "empty": "指定 Workspace 沒有 GPX；可選擇本機 GPX，僅在瀏覽器讀取。",
                "unavailable": "找不到指定 Workspace；可選擇本機 GPX，僅在瀏覽器讀取。",
            }[status],
            project_id=self.root.name,
            sources=sources,
            preferred_source_id=next((s.id for s in sources if s.workspace_role == "golden_route_reference"), None)
            if sum(s.workspace_role == "golden_route_reference" for s in sources) == 1 else None,
            next_steps=[] if sources else ["Make the selected Workspace available, or open a local GPX in the browser"],
        )

    def checkpoints(self, source_id: str) -> dict[str, Any]:
        source, _ = self.source(source_id)
        project = self.project()
        ref = project.get("overpass_aligned_checkpoint_candidates_ref") or project.get("checkpoint_candidates_ref")
        if not ref:
            return {"nodes": [], "summary": "Workspace 未指定 CP 資料。", "unmatched_count": 0}
        path = local_ref(self.root, str(ref))
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("Checkpoint artifact must be a list")
        selected_path = local_ref(self.root, source.source_ref)
        source_uris = {str(selected_path)}
        filter_ref = project.get("gpx_speed_filter_report_ref")
        if filter_ref:
            report = read_object(local_ref(self.root, str(filter_ref)))
            for item in [report.get("primary", {}), *report.get("references", [])]:
                # Hash-bound legacy URI mapping supports relocated Workspaces.
                # A matching basename or route point index is never sufficient.
                if item.get("output_sha256") == source.sha256:
                    source_uris.add(str(item.get("output_path")))
        nodes = []
        unmatched = 0
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                unmatched += 1
                continue
            provenance = record.get("provenance") or []
            if isinstance(provenance, dict):
                provenance = [provenance]
            # Index alone is not a join key. Require an exact source URI or hash.
            matches = any(
                isinstance(item, dict) and (
                    item.get("sha256") == source.sha256
                    or (isinstance(item.get("uri"), str)
                        and (str((self.root / item["uri"]).resolve()) in source_uris))
                ) for item in provenance
            )
            lat, lon = record.get("lat"), record.get("lon")
            valid = all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in (lat, lon))
            if not matches or not valid or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                unmatched += 1
                continue
            elevation = record.get("elevation_m")
            if not isinstance(elevation, (int, float)) or isinstance(elevation, bool) or not math.isfinite(elevation):
                elevation = None
            nodes.append({
                "id": f"cp:{index}:{record.get('candidate_id', '')}",
                "kind": "checkpoint", "name": str(record.get("label") or record.get("candidate_id") or "CP"),
                "lat": lat, "lon": lon, "gpx_elevation_m": None,
                "cp_elevation_m": elevation, "time": record.get("timestamp"),
                "source_ref": str(ref), "source_sha256": digest(path.read_bytes()),
                "review_state": str(record.get("review_state") or "unknown"),
                "source_provenance": provenance,
            })
        return {"nodes": nodes, "unmatched_count": unmatched,
                "summary": f"{len(nodes)} 個既有 CP 確認來源關聯；{unmatched} 個無法關聯或座標無效，未顯示。"}

    def terrain(self) -> dict[str, Any]:
        try:
            project = self.project()
            manifest = load_navigation_terrain_dem_manifest(self.root, project)
            # Validate every declared tile before advertising a usable surface.
            for tile in manifest.get("tiles", []):
                navigation_terrain_dem_tile(self.root, project, z=tile["z"], x=tile["x"], y=tile["y"])
            if not manifest.get("tiles"):
                raise ValueError("Prepared terrain contains no tiles")
            bounds = manifest["bounds_wgs84"]
            if not all(math.isfinite(float(bounds[k])) for k in ("west", "south", "east", "north")):
                raise ValueError("Invalid terrain bounds")
            vertical_datums = set()
            ref = project.get("dtm_coverage_summary_ref")
            if ref:
                coverage = read_object(local_ref(self.root, str(ref)))
                selected = set(manifest.get("source_dtm_tile_ids", []))
                for tile in coverage.get("candidate_tiles", []):
                    if tile.get("tile_id") in selected:
                        vertical_datums.add(str(tile.get("vertical_datum") or "unknown"))
            return {
                **manifest,
                "tile_url_template": "/api/terrain/{z}/{x}/{y}.png",
                "horizontal_crs": "EPSG:3857 tiles; WGS84 longitude, latitude bounds; source EPSG:3826-compatible TWD97",
                "vertical_datum": next(iter(vertical_datums)) if len(vertical_datums) == 1 else "unknown",
                "vertical_datum_basis": "selected source DTM coverage metadata; no datum conversion",
                "authority": DisplayAuthority().model_dump(),
            }
        except (FileNotFoundError, ValueError, KeyError, TypeError, OSError, TerrainDemPreparationError) as exc:
            return {"status": "unavailable", "summary": str(exc), "vertical_datum": "unknown",
                    "tile_url_template": None, "authority": DisplayAuthority().model_dump()}

    def tile(self, z: int, x: int, y: int) -> tuple[bytes, str]:
        _, path, expected = navigation_terrain_dem_tile(self.root, self.project(), z=z, x=x, y=y)
        body = path.read_bytes()
        if digest(body) != expected:
            raise ValueError("Terrain changed while reading")
        return body, expected
