from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from scout_risk.cp.dictionaries import HAZARD_KEYWORDS


@dataclass(frozen=True)
class CPNote:
    lat: float | None
    lon: float | None
    text: str
    timestamp: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class ParsedCPNote(CPNote):
    hazard_types: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)


def parse_cp_text(
    note: CPNote,
    *,
    hazard_keywords: dict[str, list[str]] | None = None,
) -> ParsedCPNote:
    hazard_keywords = hazard_keywords or HAZARD_KEYWORDS
    hazard_types: list[str] = []
    matched_keywords: list[str] = []
    for hazard_type, keywords in hazard_keywords.items():
        matches = [keyword for keyword in keywords if keyword in note.text]
        if matches:
            hazard_types.append(hazard_type)
            matched_keywords.extend(matches)
    return ParsedCPNote(
        lat=note.lat,
        lon=note.lon,
        text=note.text,
        timestamp=note.timestamp,
        source=note.source,
        hazard_types=hazard_types,
        matched_keywords=matched_keywords,
    )


def parse_cp_notes(
    notes: Iterable[CPNote],
    *,
    hazard_keywords: dict[str, list[str]] | None = None,
) -> list[ParsedCPNote]:
    return [parse_cp_text(note, hazard_keywords=hazard_keywords) for note in notes]


def load_cp_csv(path: str | Path) -> list[CPNote]:
    notes: list[CPNote] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            text = row.get("text") or row.get("note") or row.get("name") or ""
            notes.append(
                CPNote(
                    lat=_optional_float(row.get("lat") or row.get("latitude")),
                    lon=_optional_float(row.get("lon") or row.get("longitude")),
                    text=text,
                    timestamp=row.get("timestamp") or row.get("time") or None,
                    source=row.get("source") or str(path),
                )
            )
    return notes


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
