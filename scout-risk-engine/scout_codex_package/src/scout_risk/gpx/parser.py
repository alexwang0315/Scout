from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class RoutePoint:
    lat: float
    lon: float
    elevation_m: float | None = None
    time: str | None = None
    name: str | None = None


def load_gpx_points(path: str | Path) -> list[RoutePoint]:
    root = ET.parse(path).getroot()
    points: list[RoutePoint] = []
    for element in root.findall(".//{*}trkpt") + root.findall(".//{*}rtept"):
        points.append(_point_from_element(element))
    if not points:
        raise ValueError(f"GPX has no track or route points: {path}")
    return points


def load_gpx_waypoints(path: str | Path) -> list[tuple[float, float, str]]:
    root = ET.parse(path).getroot()
    waypoints: list[tuple[float, float, str]] = []
    for element in root.findall(".//{*}wpt"):
        text_parts = [
            _child_text(element, "name"),
            _child_text(element, "cmt"),
            _child_text(element, "desc"),
        ]
        text = " ".join(part for part in text_parts if part).strip()
        waypoints.append(
            (float(element.attrib["lat"]), float(element.attrib["lon"]), text)
        )
    return waypoints


def _point_from_element(element: ET.Element) -> RoutePoint:
    return RoutePoint(
        lat=float(element.attrib["lat"]),
        lon=float(element.attrib["lon"]),
        elevation_m=_optional_float(_child_text(element, "ele")),
        time=_child_text(element, "time"),
        name=_child_text(element, "name"),
    )


def _child_text(element: ET.Element, local_name: str) -> str | None:
    child = element.find(f"{{*}}{local_name}")
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def _optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None

