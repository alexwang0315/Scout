from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

from scout_energy_models import (
    BodyEnergyProviderValues,
    HeartRateSummary,
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    aggregate_sha256,
    sha256_file,
)
from scout_wearable_adapters import WearableSanitizedImportEnvelope


RawWearableSourceFormat = Literal["apple_health_export", "garmin_connect_export", "gpx", "tcx", "fit"]
ProviderArchiveSourceFormat = Literal["apple_health_export", "garmin_connect_export"]
ProviderApiFixture = Literal["apple_healthkit_api", "garmin_health_api"]

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
FIT_SESSION_GLOBAL_MESSAGE = 18
FIT_LAP_GLOBAL_MESSAGE = 19
FIT_RECORD_GLOBAL_MESSAGE = 20
FIT_FIELD_TIMESTAMP = 253
FIT_FIELD_POSITION_LAT = 0
FIT_FIELD_POSITION_LONG = 1
FIT_FIELD_ALTITUDE = 2
FIT_FIELD_HEART_RATE = 3
FIT_SESSION_FIELD_START_TIME = 2
FIT_SESSION_FIELD_TOTAL_ELAPSED_TIME = 7
FIT_SESSION_FIELD_TOTAL_TIMER_TIME = 8
FIT_SESSION_FIELD_TOTAL_DISTANCE = 9
FIT_SESSION_FIELD_AVG_HEART_RATE = 16
FIT_SESSION_FIELD_TOTAL_ASCENT = 22
FIT_SESSION_FIELD_TOTAL_DESCENT = 23
FIT_LAP_FIELD_AVG_HEART_RATE = 15
FIT_LAP_FIELD_TOTAL_ASCENT = 21
FIT_LAP_FIELD_TOTAL_DESCENT = 22


def inspect_provider_archive(
    source_path: Path,
    *,
    source_format: ProviderArchiveSourceFormat,
) -> dict[str, Any]:
    archive = _collect_provider_archive_members(source_path, source_format=source_format)
    supported_members = [member for member in archive["members"] if member["supported_for_import"]]
    deferred_members = [member for member in archive["members"] if member["deferred"]]
    unsupported_members = [
        member
        for member in archive["members"]
        if not member["supported_for_import"] and not member["deferred"]
    ]
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "provider archive manifest maps local files only and embeds no raw provider payload",
            "unsupported or deferred archive members require a later importer slice",
        ],
    ).model_dump(mode="json")
    privacy = ScoutEnergyPrivacy().model_dump(mode="json")
    boundary = ScoutEnergyBoundary().model_dump(mode="json")
    return {
        "artifact_kind": "scout_wearable_provider_archive_manifest",
        "artifact_version": "wearable_provider_archive_manifest.v1",
        "source_provider": _provider_archive_source_provider(source_format),
        "source_path": str(source_path),
        "sha256": archive["container_sha256"],
        "archive_kind": archive["archive_kind"],
        "candidate_count": len(archive["members"]),
        "supported_member_count": len(supported_members),
        "deferred_member_count": len(deferred_members),
        "unsupported_member_count": len(unsupported_members),
        "selected_member_path": supported_members[0]["member_path"] if supported_members else None,
        "members": archive["members"],
        "supported_members": supported_members,
        "deferred_members": deferred_members,
        "unsupported_members": unsupported_members,
        "data_quality": data_quality,
        "privacy": privacy,
        "boundary": boundary,
        "mutation": {
            "archive_extracted_to_workspace": False,
            "source_file_mutated": False,
            "raw_payload_committed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def summarize_raw_wearable_file(
    source_path: Path,
    *,
    source_format: RawWearableSourceFormat,
    activity_id: str,
    activity_type: str = "hiking",
) -> WearableSanitizedImportEnvelope:
    if source_format == "apple_health_export":
        return _summarize_apple_health_export(
            source_path,
            activity_id=activity_id,
            activity_type=activity_type,
        )
    if source_format == "garmin_connect_export":
        return _summarize_garmin_connect_export(
            source_path,
            activity_id=activity_id,
            activity_type=activity_type,
        )
    if source_format == "gpx":
        return _summarize_gpx(source_path, activity_id=activity_id, activity_type=activity_type)
    if source_format == "tcx":
        return _summarize_tcx(source_path, activity_id=activity_id, activity_type=activity_type)
    if source_format == "fit":
        return _summarize_fit(source_path, activity_id=activity_id, activity_type=activity_type)
    raise ValueError(f"unsupported raw wearable source format: {source_format}")


def write_sanitized_import_from_raw_file(
    source_path: Path,
    *,
    source_format: RawWearableSourceFormat,
    output_dir: Path,
    activity_id: str,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    envelope = summarize_raw_wearable_file(
        source_path,
        source_format=source_format,
        activity_id=activity_id,
        activity_type=activity_type,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_activity_slug(activity_id)}.sanitized_import.json"
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"sanitized wearable import already exists: {output_path}")
    payload = envelope.model_dump(mode="json")
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact_kind": "scout_wearable_raw_import_summary_result",
        "source_provider": payload["source_format"],
        "source_path": str(source_path),
        "sha256": sha256_file(source_path),
        "activity_id": activity_id,
        "sanitized_import_path": str(output_path),
        "sanitized_import": payload,
        "data_quality": payload["data_quality"],
        "privacy": payload["privacy"],
        "boundary": payload["boundary"],
        "mutation": {
            "sanitized_import_written": True,
            "source_file_mutated": False,
            "raw_payload_committed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def summarize_raw_wearable_file_batch(
    source_path: Path,
    *,
    source_format: RawWearableSourceFormat,
    activity_id_prefix: str,
    activity_type: str = "hiking",
) -> list[WearableSanitizedImportEnvelope]:
    if source_format == "apple_health_export":
        root = ElementTree.fromstring(source_path.read_text(encoding="utf-8"))
        return _apple_health_batch_envelopes_from_root(
            root,
            source_path=source_path,
            source_sha=sha256_file(source_path),
            activity_id_prefix=activity_id_prefix,
            activity_type=activity_type,
        )
    if source_format == "garmin_connect_export":
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        return _garmin_connect_batch_envelopes_from_payload(
            payload,
            source_path=source_path,
            source_sha=sha256_file(source_path),
            activity_id_prefix=activity_id_prefix,
            activity_type=activity_type,
        )
    raise ValueError(f"batch raw wearable source format is not supported: {source_format}")


def write_sanitized_import_batch_from_raw_file(
    source_path: Path,
    *,
    source_format: RawWearableSourceFormat,
    output_dir: Path,
    activity_id_prefix: str,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    envelopes = summarize_raw_wearable_file_batch(
        source_path,
        source_format=source_format,
        activity_id_prefix=activity_id_prefix,
        activity_type=activity_type,
    )
    results = _write_sanitized_import_envelopes(envelopes, output_dir=output_dir, overwrite=overwrite)
    providers = sorted({result["sanitized_import"]["source_format"] for result in results})
    return {
        "artifact_kind": "scout_wearable_raw_import_batch_summary_result",
        "source_provider": providers[0] if len(providers) == 1 else "mixed_raw_wearable_batch",
        "source_path": str(source_path),
        "sha256": sha256_file(source_path),
        "activity_count": len(results),
        "sanitized_import_paths": [result["sanitized_import_path"] for result in results],
        "results": results,
        "data_quality": _batch_quality_from_sanitized_imports(results),
        "privacy": ScoutEnergyPrivacy().model_dump(mode="json"),
        "boundary": ScoutEnergyBoundary().model_dump(mode="json"),
        "mutation": {
            "sanitized_imports_written": True,
            "source_file_mutated": False,
            "raw_payload_committed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_sanitized_import_batch_from_provider_api_fixture(
    source_path: Path,
    *,
    provider: ProviderApiFixture,
    output_dir: Path,
    activity_id_prefix: str,
    explicit_consent: bool,
    auth_token_ref: str | None = None,
    scopes: list[str] | None = None,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    if not explicit_consent:
        raise ValueError("explicit consent is required before provider API fixture import")
    if provider not in ("apple_healthkit_api", "garmin_health_api"):
        raise ValueError(f"provider API fixture is not supported: {provider}")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_sha = sha256_file(source_path)
    if provider == "apple_healthkit_api":
        envelopes = _apple_healthkit_api_batch_envelopes_from_payload(
            payload,
            source_path=source_path,
            source_sha=source_sha,
            activity_id_prefix=activity_id_prefix,
            activity_type=activity_type,
        )
    else:
        envelopes = _garmin_connect_batch_envelopes_from_payload(
            payload,
            source_path=source_path,
            source_sha=source_sha,
            activity_id_prefix=activity_id_prefix,
            activity_type=activity_type,
        )
    results = _write_sanitized_import_envelopes(envelopes, output_dir=output_dir, overwrite=overwrite)
    privacy = ScoutEnergyPrivacy().model_dump(mode="json")
    boundary = ScoutEnergyBoundary().model_dump(mode="json")
    authorization = {
        "provider": provider,
        "account_authorized": True,
        "explicit_consent": True,
        "network_mode": "offline_fixture",
        "real_provider_api_called": False,
        "token_value_exposed": False,
        "token_ref_sha256": _sha256_text(auth_token_ref) if auth_token_ref else None,
        "scopes": _provider_api_scopes(provider, scopes or []),
    }
    return {
        "artifact_kind": "scout_wearable_provider_api_fixture_import_result",
        "artifact_version": "wearable_provider_api_fixture_import_result.v1",
        "source_provider": f"{provider}_fixture",
        "source_path": str(source_path),
        "sha256": source_sha,
        "activity_count": len(results),
        "sanitized_import_paths": [result["sanitized_import_path"] for result in results],
        "results": results,
        "authorization": authorization,
        "data_quality": _batch_quality_from_sanitized_imports(results),
        "privacy": privacy,
        "boundary": boundary,
        "mutation": {
            "sanitized_imports_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "raw_payload_committed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_sanitized_import_batch_from_provider_archive(
    source_path: Path,
    *,
    source_format: ProviderArchiveSourceFormat,
    output_dir: Path,
    activity_id_prefix: str,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    archive_manifest = inspect_provider_archive(source_path, source_format=source_format)
    archive = _read_provider_archive_members(source_path, source_format=source_format)
    if not archive["members"]:
        raise ValueError(f"no supported provider export file found in archive: {source_path}")
    import_members = archive["members"][:1] if source_format == "apple_health_export" else archive["members"]
    envelopes: list[WearableSanitizedImportEnvelope] = []
    if source_format == "apple_health_export":
        member = import_members[0]
        if member["source_format"] == "health_auto_export_json":
            envelopes.extend(
                _health_auto_export_batch_envelopes_from_payload(
                    json.loads(member["text"]),
                    source_path=source_path,
                    source_sha=member["member_sha256"],
                    activity_id_prefix=activity_id_prefix,
                    activity_type=activity_type,
                )
            )
        else:
            envelopes.extend(
                _apple_health_batch_envelopes_from_root(
                    ElementTree.fromstring(member["text"]),
                    source_path=source_path,
                    source_sha=member["member_sha256"],
                    activity_id_prefix=activity_id_prefix,
                    activity_type=activity_type,
                )
            )
    elif source_format == "garmin_connect_export":
        multi_member = len(import_members) > 1
        for member_index, member in enumerate(import_members, start=1):
            member_prefix = (
                f"{activity_id_prefix}.{member_index:03d}"
                if multi_member
                else activity_id_prefix
            )
            if member["source_format"] == "fit":
                envelopes.append(
                    _fit_envelope_from_bytes(
                        member["data"],
                        source_path=source_path,
                        source_sha=member["member_sha256"],
                        activity_id=f"{_activity_slug(member_prefix)}.001",
                        activity_type=activity_type,
                        parser_label="raw Garmin FIT archive member local parser",
                    )
                )
            else:
                envelopes.extend(
                    _garmin_connect_batch_envelopes_from_payload(
                        json.loads(member["text"]),
                        source_path=source_path,
                        source_sha=member["member_sha256"],
                        activity_id_prefix=member_prefix,
                        activity_type=activity_type,
                    )
                )
    results = _write_sanitized_import_envelopes(envelopes, output_dir=output_dir, overwrite=overwrite)
    providers = sorted({result["sanitized_import"]["source_format"] for result in results})
    archive_members = [
        {
            "member_path": member["member_path"],
            "member_sha256": member["member_sha256"],
            "provider_role": member["provider_role"],
            "source_format": member["source_format"],
        }
        for member in import_members
    ]
    return {
        "artifact_kind": "scout_wearable_provider_archive_import_result",
        "source_provider": providers[0] if len(providers) == 1 else "mixed_provider_archive_inputs",
        "source_path": str(source_path),
        "sha256": archive["container_sha256"],
        "archive_kind": archive["archive_kind"],
        "archive_member_path": import_members[0]["member_path"],
        "archive_member_sha256": import_members[0]["member_sha256"],
        "archive_members": archive_members,
        "archive_manifest": archive_manifest,
        "activity_count": len(results),
        "sanitized_import_paths": [result["sanitized_import_path"] for result in results],
        "results": results,
        "data_quality": _batch_quality_from_sanitized_imports(results),
        "privacy": ScoutEnergyPrivacy().model_dump(mode="json"),
        "boundary": ScoutEnergyBoundary().model_dump(mode="json"),
        "mutation": {
            "sanitized_imports_written": True,
            "source_file_mutated": False,
            "archive_extracted_to_workspace": False,
            "raw_payload_committed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _write_sanitized_import_envelopes(
    envelopes: list[WearableSanitizedImportEnvelope],
    *,
    output_dir: Path,
    overwrite: bool,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for envelope in envelopes:
        payload = envelope.model_dump(mode="json")
        output_path = output_dir / f"{_activity_slug(payload['activity_id'])}.sanitized_import.json"
        if output_path.exists() and not overwrite:
            raise FileExistsError(f"sanitized wearable import already exists: {output_path}")
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        results.append(
            {
                "activity_id": payload["activity_id"],
                "sanitized_import_path": str(output_path),
                "sanitized_import": payload,
                "data_quality": payload["data_quality"],
                "privacy": payload["privacy"],
                "boundary": payload["boundary"],
            }
        )
    return results


def _read_provider_archive_members(
    source_path: Path,
    *,
    source_format: ProviderArchiveSourceFormat,
) -> dict[str, Any]:
    archive = _collect_provider_archive_members(source_path, source_format=source_format, include_text=True)
    members = [member for member in archive["members"] if member["supported_for_import"]]
    if not members:
        raise ValueError(f"no supported provider export file found in archive: {source_path}")
    return {**archive, "members": members}


def _read_provider_archive_member(source_path: Path, *, source_format: ProviderArchiveSourceFormat) -> dict[str, Any]:
    archive = _read_provider_archive_members(source_path, source_format=source_format)
    member = archive["members"][0]
    return {
        "archive_kind": archive["archive_kind"],
        "member_path": member["member_path"],
        "member_sha256": member["member_sha256"],
        "container_sha256": archive["container_sha256"],
        "text": member["text"],
    }


def _collect_provider_archive_members(
    source_path: Path,
    *,
    source_format: ProviderArchiveSourceFormat,
    include_text: bool = False,
) -> dict[str, Any]:
    if source_path.is_dir():
        candidates = _provider_archive_file_candidates(
            source_path,
            source_format=source_format,
        )
        if not candidates:
            raise ValueError(f"no supported provider export file found in archive directory: {source_path}")
        members = [
            _provider_archive_path_member(
                path,
                member_path=path.relative_to(source_path).as_posix(),
                source_format=source_format,
                include_text=include_text,
            )
            for path in candidates
        ]
        return {
            "archive_kind": "directory",
            "container_sha256": aggregate_sha256(
                [
                    str(source_path),
                    [
                        {
                            "member_path": member["member_path"],
                            "member_sha256": member["member_sha256"],
                        }
                        for member in members
                    ],
                ]
            ),
            "members": members,
        }
    if source_path.is_file() and source_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(source_path) as archive:
            member_names = _provider_archive_zip_candidates(archive, source_format=source_format)
            if not member_names:
                raise ValueError(f"no supported provider export file found in zip archive: {source_path}")
            members = [
                _provider_archive_zip_member(
                    archive,
                    member_path=member_path,
                    source_format=source_format,
                    include_text=include_text,
                )
                for member_path in member_names
            ]
        return {
            "archive_kind": "zip",
            "container_sha256": sha256_file(source_path),
            "members": members,
        }
    raise ValueError("provider archive source must be a directory or .zip file")


def _provider_archive_path_member(
    path: Path,
    *,
    member_path: str,
    source_format: ProviderArchiveSourceFormat,
    include_text: bool,
) -> dict[str, Any]:
    profile = _provider_archive_member_profile(member_path, source_format)
    member = {
        **profile,
        "member_sha256": sha256_file(path),
    }
    if include_text and profile["supported_for_import"]:
        if profile["source_format"] == "fit":
            member["data"] = path.read_bytes()
        else:
            member["text"] = path.read_text(encoding="utf-8")
    return member


def _provider_archive_zip_member(
    archive: zipfile.ZipFile,
    *,
    member_path: str,
    source_format: ProviderArchiveSourceFormat,
    include_text: bool,
) -> dict[str, Any]:
    profile = _provider_archive_member_profile(member_path, source_format)
    data = archive.read(member_path)
    member = {
        **profile,
        "member_sha256": _sha256_bytes(data),
    }
    if include_text and profile["supported_for_import"]:
        if profile["source_format"] == "fit":
            member["data"] = data
        else:
            member["text"] = data.decode("utf-8")
    return member


def _provider_archive_file_candidates(
    source_path: Path,
    *,
    source_format: ProviderArchiveSourceFormat,
) -> list[Path]:
    suffixes = _provider_archive_member_suffixes(source_format)
    return sorted(
        [
            path
            for path in source_path.rglob("*")
            if path.is_file()
            and path.suffix.lower() in suffixes
            and _provider_archive_member_allowed(path.relative_to(source_path).as_posix())
        ],
        key=lambda path: _provider_archive_member_rank(path.relative_to(source_path).as_posix(), source_format),
    )


def _provider_archive_zip_candidates(
    archive: zipfile.ZipFile,
    *,
    source_format: ProviderArchiveSourceFormat,
) -> list[str]:
    suffixes = _provider_archive_member_suffixes(source_format)
    return sorted(
        [
            name
            for name in archive.namelist()
            if Path(name).suffix.lower() in suffixes and _provider_archive_member_allowed(name)
        ],
        key=lambda name: _provider_archive_member_rank(name, source_format),
    )


def _provider_archive_member_allowed(name: str) -> bool:
    normalized = name.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return False
    return not any(part.startswith(".") or part == "__MACOSX" for part in parts)


def _provider_archive_member_suffixes(source_format: ProviderArchiveSourceFormat) -> set[str]:
    if source_format == "apple_health_export":
        return {".xml", ".json"}
    return {".json", ".fit", ".tcx", ".gpx"}


def _provider_archive_member_rank(name: str, source_format: ProviderArchiveSourceFormat) -> tuple[int, int, str]:
    profile = _provider_archive_member_profile(name, source_format)
    supported_priority = 0 if profile["supported_for_import"] else 5
    if profile["deferred"]:
        supported_priority = 7
    return (supported_priority, profile["selection_priority"], len(name), name.lower())


def _provider_archive_member_profile(name: str, source_format: ProviderArchiveSourceFormat) -> dict[str, Any]:
    lowered = name.lower()
    if source_format == "apple_health_export":
        basename = lowered.rsplit("/", 1)[-1]
        health_auto_export_json = basename.startswith("healthautoexport-") and basename.endswith(".json")
        if health_auto_export_json:
            return {
                "member_path": name,
                "source_format": "health_auto_export_json",
                "provider_role": "health_auto_export_json",
                "supported_for_import": True,
                "deferred": False,
                "selection_priority": 2,
                "selection_reason": "Health Auto Export JSON supported by local Apple wearable parser",
            }
        supported = basename == "export.xml" or (
            basename.endswith(".xml") and "export" in basename and ("apple" in lowered or "health" in lowered)
        )
        return {
            "member_path": name,
            "source_format": source_format,
            "provider_role": "apple_health_export_xml" if supported else "apple_xml_non_export",
            "supported_for_import": supported,
            "deferred": False,
            "selection_priority": 0 if basename == "export.xml" else 1 if supported else 9,
            "selection_reason": (
                "Apple Health export XML"
                if supported
                else "XML member is not recognized as an Apple Health export"
            ),
        }
    suffix = Path(lowered).suffix
    is_activity_json = suffix == ".json" and (
        "/activities/" in lowered
        or "/activitydetails/" in lowered
        or lowered.rsplit("/", 1)[-1] == "activities.json"
        or lowered.rsplit("/", 1)[-1].startswith("activity")
    )
    if is_activity_json:
        return {
            "member_path": name,
            "source_format": source_format,
            "provider_role": "garmin_activity_json",
            "supported_for_import": True,
            "deferred": False,
            "selection_priority": 0 if lowered.endswith("/activities.json") else 1,
            "selection_reason": "Garmin activity JSON supported by local parser",
        }
    if suffix == ".fit":
        return {
            "member_path": name,
            "source_format": "fit",
            "provider_role": "garmin_fit_activity_file",
            "supported_for_import": True,
            "deferred": False,
            "selection_priority": 3,
            "selection_reason": "Garmin FIT archive member supported by local FIT parser",
        }
    return {
        "member_path": name,
        "source_format": source_format,
        "provider_role": "garmin_non_activity_member",
        "supported_for_import": False,
        "deferred": False,
        "selection_priority": 9,
        "selection_reason": "Garmin archive member is not recognized as an activity import source",
    }


def _provider_archive_source_provider(source_format: ProviderArchiveSourceFormat) -> str:
    if source_format == "apple_health_export":
        return "apple_health_provider_archive"
    return "garmin_connect_provider_archive"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _summarize_gpx(
    source_path: Path,
    *,
    activity_id: str,
    activity_type: str,
) -> WearableSanitizedImportEnvelope:
    root = ElementTree.fromstring(source_path.read_text(encoding="utf-8"))
    points = []
    for point in root.findall(".//{*}trkpt"):
        lat = _float_or_none(point.attrib.get("lat"))
        lon = _float_or_none(point.attrib.get("lon"))
        ele = _float_or_none(_child_text(point, "ele"))
        time_value = _parse_time(_child_text(point, "time"))
        hr = _find_int_child(point, "hr")
        if lat is not None and lon is not None:
            points.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "ele": ele,
                    "time": time_value,
                    "hr": hr,
                }
            )
    return _envelope_from_points(
        source_format="gpx_derived_summary",
        source_path=source_path,
        activity_id=activity_id,
        activity_type=activity_type,
        points=points,
        parser_label="raw GPX local parser",
    )


def _summarize_tcx(
    source_path: Path,
    *,
    activity_id: str,
    activity_type: str,
) -> WearableSanitizedImportEnvelope:
    root = ElementTree.fromstring(source_path.read_text(encoding="utf-8"))
    points = []
    for point in root.findall(".//{*}Trackpoint"):
        lat = _float_or_none(_descendant_text(point, "LatitudeDegrees"))
        lon = _float_or_none(_descendant_text(point, "LongitudeDegrees"))
        ele = _float_or_none(_child_text(point, "AltitudeMeters"))
        time_value = _parse_time(_child_text(point, "Time"))
        hr = _find_int_child(point, "Value")
        if lat is not None and lon is not None:
            points.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "ele": ele,
                    "time": time_value,
                    "hr": hr,
                }
            )
    return _envelope_from_points(
        source_format="tcx_derived_summary",
        source_path=source_path,
        activity_id=activity_id,
        activity_type=activity_type,
        points=points,
        parser_label="raw TCX local parser",
    )


def _summarize_apple_health_export(
    source_path: Path,
    *,
    activity_id: str,
    activity_type: str,
) -> WearableSanitizedImportEnvelope:
    root = ElementTree.fromstring(source_path.read_text(encoding="utf-8"))
    workouts = _apple_matching_workouts(root, activity_type=activity_type)
    if not workouts:
        raise ValueError("raw Apple Health export local parser requires one matching workout")
    if len(workouts) > 1:
        raise ValueError("raw Apple Health export local parser requires a single matching workout")
    return _apple_health_envelope_from_workout(
        root,
        workouts[0],
        source_path=source_path,
        activity_id=activity_id,
        activity_type=activity_type,
    )


def _apple_health_envelope_from_workout(
    root: ElementTree.Element,
    workout: ElementTree.Element,
    *,
    source_path: Path,
    source_sha: str | None = None,
    activity_id: str,
    activity_type: str,
) -> WearableSanitizedImportEnvelope:
    source_sha = source_sha or sha256_file(source_path)
    start = _parse_apple_date(workout.attrib.get("startDate"))
    end = _parse_apple_date(workout.attrib.get("endDate"))
    if start is None:
        raise ValueError("raw Apple Health export workout is missing startDate")
    duration_s = _apple_duration_s(workout)
    if duration_s is None:
        duration_s = int((end - start).total_seconds()) if end else 0
    heart_rate_records = _apple_heart_rate_values(root, start=start, end=end)
    heart_rate = _heart_rate_summary(heart_rate_records, duration_s=duration_s)
    sample_cadence_s = (
        round(duration_s / (len(heart_rate_records) - 1))
        if len(heart_rate_records) > 1 and duration_s
        else None
    )
    missing_hr_seconds = 0 if heart_rate_records else duration_s
    if not heart_rate_records:
        workout_avg = _apple_workout_heart_rate_average(workout)
        if workout_avg is not None:
            heart_rate = _heart_rate_summary([round(workout_avg)], duration_s=duration_s)
            missing_hr_seconds = 0
    return WearableSanitizedImportEnvelope(
        source_format="apple_health_export_summary",
        activity_id=activity_id,
        activity_type=activity_type,
        activity_date=start.date().isoformat(),
        duration_s=duration_s,
        moving_time_s=duration_s,
        distance_m=round(_apple_distance_m(workout), 1),
        ascent_m=0,
        descent_m=0,
        rest_event_count=0,
        rest_duration_min=[],
        late_activity_fatigue_decay=None,
        session_rpe=None,
        heart_rate=heart_rate,
        body_energy_provider_values=BodyEnergyProviderValues(),
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence="medium" if heart_rate.sample_count else "low",
            gps_confidence="low",
            missing_hr_seconds=missing_hr_seconds,
            missing_hr_intervals=[],
            sample_cadence_s=sample_cadence_s,
            provider_value_confidence="low",
            limitations=[
                "raw Apple Health export local parser emitted sanitized summary only",
                f"source sha256: {source_sha}",
                "raw health payload, exact timestamps, and route geometry are not embedded",
                "Apple Health export distance is provider summary evidence, not raw track geometry",
            ],
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def _apple_healthkit_api_batch_envelopes_from_payload(
    payload: Any,
    *,
    source_path: Path,
    source_sha: str,
    activity_id_prefix: str,
    activity_type: str,
) -> list[WearableSanitizedImportEnvelope]:
    workouts = _apple_healthkit_api_workouts(payload)
    if not workouts:
        raise ValueError("Apple HealthKit API fixture requires at least one workout")
    return [
        _apple_healthkit_api_envelope_from_workout(
            workout,
            source_path=source_path,
            source_sha=source_sha,
            activity_id=f"{_activity_slug(activity_id_prefix)}.{index:03d}",
            activity_type=activity_type,
        )
        for index, workout in enumerate(workouts, start=1)
    ]


def _apple_healthkit_api_envelope_from_workout(
    workout: dict[str, Any],
    *,
    source_path: Path,
    source_sha: str,
    activity_id: str,
    activity_type: str,
) -> WearableSanitizedImportEnvelope:
    start = _parse_time(_string_from_value(_first_value(workout, "startDate", "start_time", "started_at")))
    end = _parse_time(_string_from_value(_first_value(workout, "endDate", "end_time", "ended_at")))
    if start is None:
        raise ValueError("Apple HealthKit API fixture workout is missing start time")
    duration_s = round(
        _first_number(workout, "duration_s", "durationSeconds", "duration")
        or (end - start).total_seconds()
        if end
        else 0
    )
    heart_rates = _apple_healthkit_api_heart_rates(workout, start=start, end=end)
    sample_cadence_s = (
        round(duration_s / (len(heart_rates) - 1))
        if len(heart_rates) > 1 and duration_s
        else None
    )
    missing_hr_seconds = 0 if heart_rates else duration_s
    return WearableSanitizedImportEnvelope(
        source_format="apple_healthkit_workout_summary",
        activity_id=activity_id,
        activity_type=activity_type,
        activity_date=start.date().isoformat(),
        duration_s=duration_s,
        moving_time_s=round(_first_number(workout, "moving_time_s", "movingDurationSeconds") or duration_s),
        distance_m=round(_first_number(workout, "distance_m", "distanceMeters", "totalDistance") or 0.0, 1),
        ascent_m=round(_first_number(workout, "ascent_m", "totalAscent") or 0.0, 1),
        descent_m=round(_first_number(workout, "descent_m", "totalDescent") or 0.0, 1),
        rest_event_count=0,
        rest_duration_min=[],
        late_activity_fatigue_decay=None,
        session_rpe=None,
        heart_rate=_heart_rate_summary(heart_rates, duration_s=duration_s),
        body_energy_provider_values=BodyEnergyProviderValues(),
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence="medium" if heart_rates else "low",
            gps_confidence="low",
            missing_hr_seconds=missing_hr_seconds,
            missing_hr_intervals=[],
            sample_cadence_s=sample_cadence_s,
            provider_value_confidence="low",
            limitations=[
                "Apple HealthKit API fixture emitted sanitized workout summary only",
                f"source sha256: {source_sha}",
                "raw health payload, exact timestamps, and route geometry are not embedded",
                "HealthKit distance is provider summary evidence, not raw track geometry",
            ],
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def _summarize_garmin_connect_export(
    source_path: Path,
    *,
    activity_id: str,
    activity_type: str,
) -> WearableSanitizedImportEnvelope:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    activity = _single_garmin_activity(payload)
    return _garmin_connect_envelope_from_activity(
        activity,
        source_path=source_path,
        activity_id=activity_id,
        activity_type=activity_type,
    )


def _garmin_connect_envelope_from_activity(
    activity: dict[str, Any],
    *,
    source_path: Path,
    source_sha: str | None = None,
    activity_id: str,
    activity_type: str,
) -> WearableSanitizedImportEnvelope:
    source_sha = source_sha or sha256_file(source_path)
    start = _parse_garmin_time(_first_value(activity, "startTimeGMT", "startTimeLocal", "startTime", "beginTimestamp"))
    if start is None:
        raise ValueError("raw Garmin Connect export local parser requires a start time")
    duration_s = round(_first_number(activity, "duration", "elapsedDuration", "elapsedDurationSeconds") or 0)
    moving_time_s = round(_first_number(activity, "movingDuration", "movingDurationSeconds", "movingTime") or duration_s)
    heart_rates, sample_cadence_s = _garmin_heart_rate_values(activity, duration_s=duration_s)
    heart_rate = _heart_rate_summary(heart_rates, duration_s=duration_s)
    provider_values = _garmin_provider_values(activity)
    has_provider_values = any(
        value is not None
        for value in (
            provider_values.garmin_body_battery_start,
            provider_values.garmin_body_battery_end,
            provider_values.garmin_stress_avg,
        )
    )
    missing_hr_seconds = 0 if heart_rate.sample_count else duration_s
    return WearableSanitizedImportEnvelope(
        source_format="garmin_connect_activity_summary",
        activity_id=activity_id,
        activity_type=activity_type,
        activity_date=start.date().isoformat(),
        duration_s=duration_s,
        moving_time_s=moving_time_s,
        distance_m=round(_first_number(activity, "distance", "distanceMeters", "sumDistance") or 0.0, 1),
        ascent_m=round(_first_number(activity, "elevationGain", "elevationGainMeters", "totalAscent") or 0.0, 1),
        descent_m=round(_first_number(activity, "elevationLoss", "elevationLossMeters", "totalDescent") or 0.0, 1),
        rest_event_count=0,
        rest_duration_min=[],
        late_activity_fatigue_decay=None,
        session_rpe=None,
        heart_rate=heart_rate,
        body_energy_provider_values=provider_values,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence="medium" if heart_rate.sample_count else "low",
            gps_confidence=(
                "medium"
                if _first_number(activity, "distance", "distanceMeters", "sumDistance") is not None
                else "low"
            ),
            missing_hr_seconds=missing_hr_seconds,
            missing_hr_intervals=[],
            sample_cadence_s=sample_cadence_s,
            provider_value_confidence="medium" if has_provider_values else "low",
            limitations=[
                "raw Garmin Connect export local parser emitted sanitized summary only",
                f"source sha256: {source_sha}",
                "raw provider payload, exact timestamps, and route geometry are not embedded",
                "Garmin body battery and stress are provider values only, not Scout truth",
            ],
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def _apple_health_batch_envelopes_from_root(
    root: ElementTree.Element,
    *,
    source_path: Path,
    source_sha: str,
    activity_id_prefix: str,
    activity_type: str,
) -> list[WearableSanitizedImportEnvelope]:
    workouts = _apple_matching_workouts(root, activity_type=activity_type)
    if not workouts:
        raise ValueError("raw Apple Health export batch parser requires at least one matching workout")
    return [
        _apple_health_envelope_from_workout(
            root,
            workout,
            source_path=source_path,
            source_sha=source_sha,
            activity_id=f"{_activity_slug(activity_id_prefix)}.{index:03d}",
            activity_type=activity_type,
        )
        for index, workout in enumerate(workouts, start=1)
    ]


def _health_auto_export_batch_envelopes_from_payload(
    payload: Any,
    *,
    source_path: Path,
    source_sha: str,
    activity_id_prefix: str,
    activity_type: str,
) -> list[WearableSanitizedImportEnvelope]:
    workouts = _health_auto_export_workouts(payload)
    if not workouts:
        raise ValueError("Health Auto Export JSON parser requires at least one workout")
    return [
        _health_auto_export_envelope_from_workout(
            workout,
            source_path=source_path,
            source_sha=source_sha,
            activity_id=f"{_activity_slug(activity_id_prefix)}.{index:03d}",
            activity_type=activity_type,
        )
        for index, workout in enumerate(workouts, start=1)
    ]


def _health_auto_export_workouts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if isinstance(payload, dict) and isinstance(payload.get("workouts"), list):
        workouts = payload["workouts"]
    elif isinstance(payload, list):
        workouts = payload
    else:
        raise ValueError("Health Auto Export JSON parser requires data.workouts")
    if not all(isinstance(workout, dict) for workout in workouts):
        raise ValueError("Health Auto Export JSON parser requires workout objects")
    return workouts


def _health_auto_export_envelope_from_workout(
    workout: dict[str, Any],
    *,
    source_path: Path,
    source_sha: str,
    activity_id: str,
    activity_type: str,
) -> WearableSanitizedImportEnvelope:
    start = _parse_apple_date(_string_from_value(workout.get("start")))
    end = _parse_apple_date(_string_from_value(workout.get("end")))
    if start is None:
        raise ValueError("Health Auto Export workout is missing start")
    duration_s = round(
        _first_number(workout, "duration")
        or ((end - start).total_seconds() if end else 0)
    )
    heart_rates, sample_cadence_s = _health_auto_export_heart_rates(workout, duration_s=duration_s)
    heart_rate = _heart_rate_summary(heart_rates, duration_s=duration_s)
    missing_hr_seconds = 0 if heart_rate.sample_count else duration_s
    workout_type = _health_auto_export_activity_type(workout, default=activity_type)
    return WearableSanitizedImportEnvelope(
        source_format="apple_health_export_summary",
        activity_id=activity_id,
        activity_type=workout_type,
        activity_date=start.date().isoformat(),
        duration_s=duration_s,
        moving_time_s=duration_s,
        distance_m=round(_health_auto_export_quantity(workout.get("distance"), default_units="km", target_units="m") or 0.0, 1),
        ascent_m=round(_health_auto_export_quantity(workout.get("elevationUp"), default_units="m", target_units="m") or 0.0, 1),
        descent_m=0.0,
        rest_event_count=0,
        rest_duration_min=[],
        late_activity_fatigue_decay=None,
        session_rpe=None,
        heart_rate=heart_rate,
        body_energy_provider_values=BodyEnergyProviderValues(),
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence="medium" if heart_rate.sample_count else "low",
            gps_confidence="medium" if workout.get("route") else "low",
            missing_hr_seconds=missing_hr_seconds,
            missing_hr_intervals=[],
            sample_cadence_s=sample_cadence_s,
            provider_value_confidence="low",
            limitations=[
                "Health Auto Export JSON parser emitted sanitized workout summary only",
                f"source sha256: {source_sha}",
                "raw health payload, route geometry, exact timestamps, and source samples are not embedded",
                "Health Auto Export route GPX members remain local source material, not Scout runtime truth",
            ],
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def _health_auto_export_activity_type(workout: dict[str, Any], *, default: str) -> str:
    name = str(workout.get("name") or "").lower()
    if "跑" in name or "run" in name:
        return "running"
    if "步行" in name or "walk" in name:
        return "walking"
    if "hike" in name or "登山" in name:
        return "hiking"
    if "皮拉提斯" in name or "pilates" in name:
        return "cross_training"
    return default


def _health_auto_export_heart_rates(workout: dict[str, Any], *, duration_s: int) -> tuple[list[int], int | None]:
    samples = workout.get("heartRateData")
    heart_rates: list[int] = []
    sample_times: list[datetime] = []
    if isinstance(samples, list):
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            bpm = _number_from_value(_first_value(sample, "Avg", "avg", "qty", "value"))
            if bpm is not None:
                heart_rates.append(round(bpm))
            sample_time = _parse_apple_date(_string_from_value(sample.get("date")))
            if sample_time is not None:
                sample_times.append(sample_time)
    if not heart_rates:
        avg_bpm = _health_auto_export_quantity(workout.get("avgHeartRate"), default_units="bpm", target_units="bpm")
        if avg_bpm is None and isinstance(workout.get("heartRate"), dict):
            avg_bpm = _health_auto_export_quantity(
                workout["heartRate"].get("avg"),
                default_units="bpm",
                target_units="bpm",
            )
        if avg_bpm is not None:
            heart_rates.append(round(avg_bpm))
    if len(sample_times) > 1:
        ordered = sorted(sample_times)
        deltas = [
            (current - previous).total_seconds()
            for previous, current in zip(ordered, ordered[1:])
            if current > previous
        ]
        if deltas:
            return heart_rates, max(1, round(sum(deltas) / len(deltas)))
    cadence = round(duration_s / (len(heart_rates) - 1)) if len(heart_rates) > 1 and duration_s else None
    return heart_rates, cadence


def _health_auto_export_quantity(value: Any, *, default_units: str, target_units: str) -> float | None:
    units = default_units
    raw: Any = value
    if isinstance(value, dict):
        raw = value.get("qty", value.get("value"))
        units = str(value.get("units") or default_units)
    number = _number_from_value(raw)
    if number is None:
        return None
    normalized_units = units.lower()
    if target_units == "m":
        if normalized_units == "km":
            return number * 1000
        return number
    return number


def _garmin_connect_batch_envelopes_from_payload(
    payload: Any,
    *,
    source_path: Path,
    source_sha: str,
    activity_id_prefix: str,
    activity_type: str,
) -> list[WearableSanitizedImportEnvelope]:
    activities = _garmin_activities(payload)
    if not activities:
        raise ValueError("raw Garmin Connect export batch parser requires at least one activity")
    return [
        _garmin_connect_envelope_from_activity(
            activity,
            source_path=source_path,
            source_sha=source_sha,
            activity_id=f"{_activity_slug(activity_id_prefix)}.{index:03d}",
            activity_type=activity_type,
        )
        for index, activity in enumerate(activities, start=1)
    ]


def _summarize_fit(
    source_path: Path,
    *,
    activity_id: str,
    activity_type: str,
) -> WearableSanitizedImportEnvelope:
    return _fit_envelope_from_bytes(
        source_path.read_bytes(),
        source_path=source_path,
        source_sha=sha256_file(source_path),
        activity_id=activity_id,
        activity_type=activity_type,
        parser_label="raw FIT local parser",
    )


def _fit_points(source_path: Path) -> list[dict[str, Any]]:
    return _fit_points_from_bytes(source_path.read_bytes())


def _fit_envelope_from_bytes(
    payload: bytes,
    *,
    source_path: Path,
    source_sha: str,
    activity_id: str,
    activity_type: str,
    parser_label: str,
) -> WearableSanitizedImportEnvelope:
    activity = _fit_activity_from_bytes(payload)
    if activity["points"]:
        return _envelope_from_points(
            source_format="fit_derived_summary",
            source_path=source_path,
            source_sha=source_sha,
            activity_id=activity_id,
            activity_type=activity_type,
            points=activity["points"],
            parser_label=parser_label,
        )
    if activity["sessions"]:
        return _envelope_from_fit_session(
            activity["sessions"][0],
            source_path=source_path,
            source_sha=source_sha,
            activity_id=activity_id,
            activity_type=activity_type,
            parser_label=parser_label,
        )
    if activity["laps"]:
        return _envelope_from_fit_session(
            _fit_session_from_laps(activity["laps"]),
            source_path=source_path,
            source_sha=source_sha,
            activity_id=activity_id,
            activity_type=activity_type,
            parser_label=parser_label,
            summary_label="lap summary",
        )
    raise ValueError(f"{parser_label} requires record points, a session summary, or a lap summary")


def _fit_activity_from_bytes(payload: bytes) -> dict[str, Any]:
    data = _fit_data_section_from_bytes(payload)
    return _parse_fit_data_section(data)


def _fit_points_from_bytes(payload: bytes) -> list[dict[str, Any]]:
    return _fit_activity_from_bytes(payload)["points"]


def _fit_data_section_from_bytes(payload: bytes) -> bytes:
    if len(payload) < 12:
        raise ValueError("raw FIT local parser requires a complete FIT header")
    header_size = payload[0]
    if header_size not in (12, 14):
        raise ValueError(f"unsupported FIT header size: {header_size}")
    if len(payload) < header_size:
        raise ValueError("raw FIT local parser found truncated FIT header")
    if payload[8:12] != b".FIT":
        raise ValueError("raw FIT local parser requires .FIT signature")
    data_size = struct.unpack_from("<I", payload, 4)[0]
    data_start = header_size
    data_end = data_start + data_size
    if len(payload) < data_end:
        raise ValueError("raw FIT local parser found truncated data section")
    return payload[data_start:data_end]


def _envelope_from_fit_session(
    session: dict[str, Any],
    *,
    source_path: Path,
    source_sha: str,
    activity_id: str,
    activity_type: str,
    parser_label: str,
    summary_label: str = "session summary",
) -> WearableSanitizedImportEnvelope:
    start = session.get("start_time") or session.get("timestamp")
    if start is None:
        start = datetime(1970, 1, 1, tzinfo=timezone.utc)
    duration_s = round(session.get("total_elapsed_time_s") or session.get("total_timer_time_s") or 0)
    moving_time_s = round(session.get("total_timer_time_s") or duration_s)
    avg_hr = session.get("avg_heart_rate")
    heart_rates = [avg_hr] if avg_hr is not None else []
    missing_hr_seconds = 0 if heart_rates else duration_s
    return WearableSanitizedImportEnvelope(
        source_format="fit_derived_summary",
        activity_id=activity_id,
        activity_type=activity_type,
        activity_date=start.date().isoformat(),
        duration_s=duration_s,
        moving_time_s=moving_time_s,
        distance_m=round(session.get("total_distance_m") or 0.0, 1),
        ascent_m=round(session.get("total_ascent_m") or 0.0, 1),
        descent_m=round(session.get("total_descent_m") or 0.0, 1),
        rest_event_count=0,
        rest_duration_min=[],
        late_activity_fatigue_decay=None,
        session_rpe=None,
        heart_rate=_heart_rate_summary(heart_rates, duration_s=duration_s),
        body_energy_provider_values=BodyEnergyProviderValues(),
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence="low" if avg_hr is None else "medium",
            gps_confidence="low",
            missing_hr_seconds=missing_hr_seconds,
            missing_hr_intervals=[],
            sample_cadence_s=None,
            provider_value_confidence="low",
            limitations=[
                f"{parser_label} emitted sanitized {summary_label} only",
                f"source sha256: {source_sha}",
                "raw FIT records, exact timestamps, and source payload are not embedded",
                f"FIT {summary_label} has no route geometry",
            ],
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def _parse_fit_data_section(data: bytes) -> dict[str, Any]:
    definitions: dict[int, dict[str, Any]] = {}
    points: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    laps: list[dict[str, Any]] = []
    offset = 0
    while offset < len(data):
        header = data[offset]
        offset += 1
        if header & 0x80:
            raise ValueError("compressed timestamp FIT headers are not supported by the local parser")
        local_message_type = header & 0x0F
        if header & 0x40:
            if header & 0x20:
                raise ValueError("FIT developer data definitions are not supported by the local parser")
            definition, offset = _parse_fit_definition(data, offset)
            definitions[local_message_type] = definition
            continue
        definition = definitions.get(local_message_type)
        if definition is None:
            raise ValueError(f"FIT data message uses undefined local message type: {local_message_type}")
        record, offset = _parse_fit_data_message(data, offset, definition)
        if definition["global_message_number"] == FIT_RECORD_GLOBAL_MESSAGE:
            point = _fit_record_point(record)
            if point is not None:
                points.append(point)
        elif definition["global_message_number"] == FIT_SESSION_GLOBAL_MESSAGE:
            session = _fit_session_summary(record)
            if session is not None:
                sessions.append(session)
        elif definition["global_message_number"] == FIT_LAP_GLOBAL_MESSAGE:
            lap = _fit_lap_summary(record)
            if lap is not None:
                laps.append(lap)
    return {"points": points, "sessions": sessions, "laps": laps}


def _parse_fit_definition(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    if offset + 5 > len(data):
        raise ValueError("truncated FIT definition message")
    architecture = data[offset + 1]
    if architecture == 0:
        endian = "<"
    elif architecture == 1:
        endian = ">"
    else:
        raise ValueError(f"unsupported FIT architecture byte: {architecture}")
    global_message_number = struct.unpack_from(f"{endian}H", data, offset + 2)[0]
    field_count = data[offset + 4]
    offset += 5
    fields: list[dict[str, int]] = []
    for _ in range(field_count):
        if offset + 3 > len(data):
            raise ValueError("truncated FIT field definition")
        fields.append(
            {
                "field_number": data[offset],
                "size": data[offset + 1],
                "base_type": data[offset + 2],
            }
        )
        offset += 3
    return (
        {
            "global_message_number": global_message_number,
            "endian": endian,
            "fields": fields,
        },
        offset,
    )


def _parse_fit_data_message(
    data: bytes,
    offset: int,
    definition: dict[str, Any],
) -> tuple[dict[int, Any], int]:
    values: dict[int, Any] = {}
    for field in definition["fields"]:
        size = field["size"]
        if offset + size > len(data):
            raise ValueError("truncated FIT data message")
        raw_value = data[offset : offset + size]
        offset += size
        values[field["field_number"]] = _decode_fit_value(
            raw_value,
            base_type=field["base_type"],
            endian=definition["endian"],
        )
    return values, offset


def _decode_fit_value(raw_value: bytes, *, base_type: int, endian: str) -> int | None:
    base_number = base_type & 0x1F
    if base_number == 2 and len(raw_value) == 1:
        value = raw_value[0]
        return None if value == 0xFF else value
    if base_number == 4 and len(raw_value) == 2:
        value = struct.unpack(f"{endian}H", raw_value)[0]
        return None if value == 0xFFFF else value
    if base_number == 5 and len(raw_value) == 4:
        value = struct.unpack(f"{endian}i", raw_value)[0]
        return None if value == 0x7FFFFFFF else value
    if base_number == 6 and len(raw_value) == 4:
        value = struct.unpack(f"{endian}I", raw_value)[0]
        return None if value == 0xFFFFFFFF else value
    return None


def _fit_record_point(record: dict[int, Any]) -> dict[str, Any] | None:
    lat = record.get(FIT_FIELD_POSITION_LAT)
    lon = record.get(FIT_FIELD_POSITION_LONG)
    if lat is None or lon is None:
        return None
    altitude = record.get(FIT_FIELD_ALTITUDE)
    timestamp = record.get(FIT_FIELD_TIMESTAMP)
    return {
        "lat": _semicircles_to_degrees(lat),
        "lon": _semicircles_to_degrees(lon),
        "ele": _fit_altitude_m(altitude) if altitude is not None else None,
        "time": FIT_EPOCH + timedelta(seconds=timestamp) if timestamp is not None else None,
        "hr": record.get(FIT_FIELD_HEART_RATE),
    }


def _fit_session_summary(record: dict[int, Any]) -> dict[str, Any] | None:
    start_time = record.get(FIT_SESSION_FIELD_START_TIME)
    timestamp = record.get(FIT_FIELD_TIMESTAMP)
    elapsed = record.get(FIT_SESSION_FIELD_TOTAL_ELAPSED_TIME)
    timer = record.get(FIT_SESSION_FIELD_TOTAL_TIMER_TIME)
    distance = record.get(FIT_SESSION_FIELD_TOTAL_DISTANCE)
    if start_time is None and timestamp is None and elapsed is None and distance is None:
        return None
    return {
        "start_time": FIT_EPOCH + timedelta(seconds=start_time) if start_time is not None else None,
        "timestamp": FIT_EPOCH + timedelta(seconds=timestamp) if timestamp is not None else None,
        "total_elapsed_time_s": _fit_scaled_seconds(elapsed),
        "total_timer_time_s": _fit_scaled_seconds(timer),
        "total_distance_m": (distance / 100.0) if distance is not None else None,
        "total_ascent_m": record.get(FIT_SESSION_FIELD_TOTAL_ASCENT),
        "total_descent_m": record.get(FIT_SESSION_FIELD_TOTAL_DESCENT),
        "avg_heart_rate": record.get(FIT_SESSION_FIELD_AVG_HEART_RATE),
    }


def _fit_lap_summary(record: dict[int, Any]) -> dict[str, Any] | None:
    start_time = record.get(FIT_SESSION_FIELD_START_TIME)
    timestamp = record.get(FIT_FIELD_TIMESTAMP)
    elapsed = record.get(FIT_SESSION_FIELD_TOTAL_ELAPSED_TIME)
    timer = record.get(FIT_SESSION_FIELD_TOTAL_TIMER_TIME)
    distance = record.get(FIT_SESSION_FIELD_TOTAL_DISTANCE)
    if start_time is None and timestamp is None and elapsed is None and distance is None:
        return None
    return {
        "start_time": FIT_EPOCH + timedelta(seconds=start_time) if start_time is not None else None,
        "timestamp": FIT_EPOCH + timedelta(seconds=timestamp) if timestamp is not None else None,
        "total_elapsed_time_s": _fit_scaled_seconds(elapsed),
        "total_timer_time_s": _fit_scaled_seconds(timer),
        "total_distance_m": (distance / 100.0) if distance is not None else None,
        "total_ascent_m": record.get(FIT_LAP_FIELD_TOTAL_ASCENT),
        "total_descent_m": record.get(FIT_LAP_FIELD_TOTAL_DESCENT),
        "avg_heart_rate": record.get(FIT_LAP_FIELD_AVG_HEART_RATE),
    }


def _fit_session_from_laps(laps: list[dict[str, Any]]) -> dict[str, Any]:
    timer_s = sum(lap.get("total_timer_time_s") or 0 for lap in laps)
    weighted_hr = sum(
        (lap.get("avg_heart_rate") or 0) * (lap.get("total_timer_time_s") or 0)
        for lap in laps
        if lap.get("avg_heart_rate") is not None
    )
    avg_hr = round(weighted_hr / timer_s) if timer_s and weighted_hr else None
    return {
        "start_time": min((lap["start_time"] for lap in laps if lap.get("start_time")), default=None),
        "timestamp": max((lap["timestamp"] for lap in laps if lap.get("timestamp")), default=None),
        "total_elapsed_time_s": sum(lap.get("total_elapsed_time_s") or 0 for lap in laps),
        "total_timer_time_s": timer_s,
        "total_distance_m": sum(lap.get("total_distance_m") or 0 for lap in laps),
        "total_ascent_m": sum(lap.get("total_ascent_m") or 0 for lap in laps),
        "total_descent_m": sum(lap.get("total_descent_m") or 0 for lap in laps),
        "avg_heart_rate": avg_hr,
    }


def _fit_scaled_seconds(value: int | None) -> float | None:
    return (value / 1000.0) if value is not None else None


def _semicircles_to_degrees(value: int) -> float:
    return value * (180.0 / 2**31)


def _fit_altitude_m(value: int) -> float:
    return (value / 5.0) - 500.0


def _apple_workout_matches_activity_type(element: ElementTree.Element, activity_type: str) -> bool:
    workout_type = element.attrib.get("workoutActivityType", "")
    activity = activity_type.lower()
    if activity == "hiking":
        return workout_type == "HKWorkoutActivityTypeHiking"
    if activity == "walking":
        return workout_type == "HKWorkoutActivityTypeWalking"
    if activity == "running":
        return workout_type == "HKWorkoutActivityTypeRunning"
    if activity == "cycling":
        return workout_type == "HKWorkoutActivityTypeCycling"
    return True


def _apple_matching_workouts(
    root: ElementTree.Element,
    *,
    activity_type: str,
) -> list[ElementTree.Element]:
    return [
        element
        for element in root.iter()
        if _local_name(element.tag) == "Workout"
        and _apple_workout_matches_activity_type(element, activity_type)
    ]


def _parse_apple_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S %Z"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    return _parse_time(value)


def _apple_duration_s(workout: ElementTree.Element) -> int | None:
    value = workout.attrib.get("duration")
    if value is None:
        return None
    duration = float(value)
    unit = workout.attrib.get("durationUnit", "min").lower()
    if unit in {"s", "sec", "second", "seconds"}:
        return round(duration)
    if unit in {"h", "hr", "hour", "hours"}:
        return round(duration * 3600)
    return round(duration * 60)


def _apple_distance_m(workout: ElementTree.Element) -> float:
    value = workout.attrib.get("totalDistance")
    if value is None:
        return 0.0
    distance = float(value)
    unit = workout.attrib.get("totalDistanceUnit", "m").lower()
    if unit in {"km", "kilometer", "kilometers"}:
        return distance * 1000
    if unit in {"mi", "mile", "miles"}:
        return distance * 1609.344
    if unit in {"ft", "foot", "feet"}:
        return distance * 0.3048
    return distance


def _apple_heart_rate_values(
    root: ElementTree.Element,
    *,
    start: datetime,
    end: datetime | None,
) -> list[int]:
    records: list[tuple[datetime, int]] = []
    for element in root.iter():
        if _local_name(element.tag) != "Record":
            continue
        if element.attrib.get("type") != "HKQuantityTypeIdentifierHeartRate":
            continue
        recorded_at = _parse_apple_date(element.attrib.get("startDate"))
        if recorded_at is None:
            continue
        if recorded_at < start or (end and recorded_at > end):
            continue
        value = _float_or_none(element.attrib.get("value"))
        if value is not None:
            records.append((recorded_at, round(value)))
    return [value for _, value in sorted(records, key=lambda item: item[0])]


def _apple_workout_heart_rate_average(workout: ElementTree.Element) -> float | None:
    for element in workout.iter():
        if _local_name(element.tag) != "WorkoutStatistics":
            continue
        if element.attrib.get("type") == "HKQuantityTypeIdentifierHeartRate":
            return _float_or_none(element.attrib.get("average"))
    return None


def _apple_healthkit_api_workouts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("workouts"), list):
        workouts = payload["workouts"]
    elif isinstance(payload, dict) and isinstance(payload.get("workout"), dict):
        workouts = [payload["workout"]]
    elif isinstance(payload, list):
        workouts = payload
    elif isinstance(payload, dict):
        workouts = [payload]
    else:
        raise ValueError("Apple HealthKit API fixture requires workout objects")
    if not all(isinstance(workout, dict) for workout in workouts):
        raise ValueError("Apple HealthKit API fixture requires workout objects")
    return workouts


def _apple_healthkit_api_heart_rates(
    workout: dict[str, Any],
    *,
    start: datetime,
    end: datetime | None,
) -> list[int]:
    samples = _first_value(workout, "heart_rate_samples", "heartRateSamples", "heart_rates")
    records: list[tuple[datetime, int]] = []
    if not isinstance(samples, list):
        return []
    for sample in samples:
        recorded_at: datetime | None = None
        bpm: float | None = None
        if isinstance(sample, dict):
            recorded_at = _parse_time(
                _string_from_value(_first_value(sample, "startDate", "time", "recorded_at"))
            )
            bpm = _number_from_value(_first_value(sample, "bpm", "heartRate", "value"))
        elif isinstance(sample, (list, tuple)) and len(sample) >= 2:
            recorded_at = _parse_time(_string_from_value(sample[0]))
            bpm = _number_from_value(sample[1])
        else:
            bpm = _number_from_value(sample)
        if bpm is None:
            continue
        if recorded_at is not None and end is not None and not (start <= recorded_at <= end):
            continue
        sort_time = recorded_at or start
        records.append((sort_time, round(bpm)))
    return [bpm for _, bpm in sorted(records, key=lambda item: item[0])]


def _provider_api_scopes(provider: ProviderApiFixture, scopes: list[str]) -> list[str]:
    if provider == "apple_healthkit_api":
        mapped = []
        for scope in scopes:
            normalized = scope.strip()
            if normalized == "HKWorkoutType":
                mapped.append("workout:read")
            elif normalized == "HKQuantityTypeIdentifierHeartRate":
                mapped.append("heart_rate:read")
            elif normalized:
                mapped.append(normalized)
        return sorted(set(mapped))
    return sorted(scopes)


def _single_garmin_activity(payload: Any) -> dict[str, Any]:
    activities = _garmin_activities(payload)
    if len(activities) != 1:
        raise ValueError("raw Garmin Connect export local parser requires one activity")
    return activities[0]


def _garmin_activities(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        activities = payload
    elif isinstance(payload, dict) and isinstance(payload.get("activities"), list):
        activities = payload["activities"]
    elif isinstance(payload, dict) and isinstance(payload.get("activity"), dict):
        activities = [payload["activity"]]
    elif isinstance(payload, dict):
        activities = [payload]
    else:
        raise ValueError("raw Garmin Connect export local parser requires an activity object")
    if not all(isinstance(activity, dict) for activity in activities):
        raise ValueError("raw Garmin Connect export local parser requires activity objects")
    return activities


def _parse_garmin_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp_s = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(timestamp_s, tz=timezone.utc)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return _parse_time(normalized)
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S %z"):
        try:
            return datetime.strptime(normalized, pattern)
        except ValueError:
            continue
    raise ValueError(f"unsupported Garmin Connect timestamp format: {value}")


def _garmin_heart_rate_values(activity: dict[str, Any], *, duration_s: int) -> tuple[list[int], int | None]:
    samples = _first_value(activity, "heartRateSamples", "heartRateValues", "heartRates")
    heart_rates: list[int] = []
    offsets: list[int] = []
    if isinstance(samples, list):
        for sample in samples:
            offset: float | None = None
            bpm: float | None = None
            if isinstance(sample, dict):
                bpm = _number_from_value(_first_value(sample, "bpm", "heartRate", "hr", "value"))
                offset = _number_from_value(
                    _first_value(sample, "offset_s", "timeOffsetSeconds", "startTimeOffsetInSeconds", "seconds")
                )
            elif isinstance(sample, (list, tuple)) and len(sample) >= 2:
                offset = _number_from_value(sample[0])
                bpm = _number_from_value(sample[1])
            else:
                bpm = _number_from_value(sample)
            if bpm is not None:
                heart_rates.append(round(bpm))
                if offset is not None:
                    offsets.append(round(offset))
    if not heart_rates:
        avg_bpm = _first_number(activity, "averageHR", "averageHeartRate", "avgHr", "avgHeartRate")
        if avg_bpm is not None:
            heart_rates.append(round(avg_bpm))
    if len(offsets) > 1:
        ordered_offsets = sorted(offsets)
        deltas = [
            current - previous
            for previous, current in zip(ordered_offsets, ordered_offsets[1:])
            if current > previous
        ]
        if deltas:
            return heart_rates, round(sum(deltas) / len(deltas))
    cadence = round(duration_s / (len(heart_rates) - 1)) if len(heart_rates) > 1 and duration_s else None
    return heart_rates, cadence


def _garmin_provider_values(activity: dict[str, Any]) -> BodyEnergyProviderValues:
    return BodyEnergyProviderValues(
        garmin_body_battery_start=_bounded_int(
            _first_number(
                activity,
                "garmin_body_battery_start",
                "bodyBatteryStart",
                "bodyBattery.start",
                "bodyBattery.startValue",
                "summaryDTO.bodyBatteryStart",
            )
        ),
        garmin_body_battery_end=_bounded_int(
            _first_number(
                activity,
                "garmin_body_battery_end",
                "bodyBatteryEnd",
                "bodyBattery.end",
                "bodyBattery.endValue",
                "summaryDTO.bodyBatteryEnd",
            )
        ),
        garmin_stress_avg=_bounded_int(
            _first_number(
                activity,
                "garmin_stress_avg",
                "stressAvg",
                "averageStress",
                "stress.avg",
                "stress.average",
                "avgStressLevel",
                "summaryDTO.stressAvg",
            )
        ),
        source_value_only=True,
        scout_truth=False,
    )


def _first_value(payload: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value = _nested_value(payload, path)
        if value is not None:
            return value
    return None


def _first_number(payload: dict[str, Any], *paths: str) -> float | None:
    value = _first_value(payload, *paths)
    return _number_from_value(value)


def _nested_value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _string_from_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _number_from_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _bounded_int(value: float | None, *, lower: int = 0, upper: int = 100) -> int | None:
    if value is None:
        return None
    rounded = round(value)
    return rounded if lower <= rounded <= upper else None


def _envelope_from_points(
    *,
    source_format: str,
    source_path: Path,
    source_sha: str | None = None,
    activity_id: str,
    activity_type: str,
    points: list[dict[str, Any]],
    parser_label: str,
) -> WearableSanitizedImportEnvelope:
    source_sha = source_sha or sha256_file(source_path)
    if len(points) < 2:
        raise ValueError(f"{parser_label} requires at least two track points")
    times = [point["time"] for point in points if point.get("time")]
    start = min(times) if times else None
    end = max(times) if times else None
    duration_s = int((end - start).total_seconds()) if start and end else 0
    elevations = [point["ele"] for point in points if point.get("ele") is not None]
    ascent_m, descent_m = _ascent_descent(elevations)
    heart_rates = [point["hr"] for point in points if point.get("hr") is not None]
    missing_hr_seconds = 0 if heart_rates else duration_s
    sample_cadence_s = round(duration_s / (len(heart_rates) - 1)) if len(heart_rates) > 1 and duration_s else None
    return WearableSanitizedImportEnvelope(
        source_format=source_format,
        activity_id=activity_id,
        activity_type=activity_type,
        activity_date=(start.date().isoformat() if start else "1970-01-01"),
        duration_s=duration_s,
        moving_time_s=duration_s,
        distance_m=round(_distance_m(points), 1),
        ascent_m=round(ascent_m, 1),
        descent_m=round(descent_m, 1),
        rest_event_count=0,
        rest_duration_min=[],
        late_activity_fatigue_decay=None,
        session_rpe=None,
        heart_rate=_heart_rate_summary(heart_rates, duration_s=duration_s),
        body_energy_provider_values=BodyEnergyProviderValues(),
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence="medium" if heart_rates else "low",
            gps_confidence="medium",
            missing_hr_seconds=missing_hr_seconds,
            missing_hr_intervals=[],
            sample_cadence_s=sample_cadence_s,
            provider_value_confidence="low",
            limitations=[
                f"{parser_label} emitted sanitized summary only",
                f"source sha256: {source_sha}",
                "raw track geometry, exact timestamps, and source payload are not embedded",
            ],
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def _batch_quality_from_sanitized_imports(results: list[dict[str, Any]]) -> dict[str, Any]:
    order = {"low": 0, "medium": 1, "high": 2}
    qualities = [result["data_quality"] for result in results]
    limitations = sorted(
        {
            limitation
            for quality in qualities
            for limitation in quality.get("limitations", [])
        }
    )
    return ScoutEnergyDataQuality(
        heart_rate_confidence=min(
            (quality.get("heart_rate_confidence", "low") for quality in qualities),
            key=order.get,
        ),
        gps_confidence=min(
            (quality.get("gps_confidence", "low") for quality in qualities),
            key=order.get,
        ),
        missing_hr_seconds=sum(quality.get("missing_hr_seconds", 0) for quality in qualities),
        provider_value_confidence=min(
            (quality.get("provider_value_confidence", "low") for quality in qualities),
            key=order.get,
        ),
        limitations=limitations,
    ).model_dump(mode="json")


def _heart_rate_summary(heart_rates: list[int], *, duration_s: int) -> HeartRateSummary:
    if not heart_rates:
        return HeartRateSummary(sample_count=0, avg_bpm=None, p90_bpm=None, zone_minutes={}, samples=[])
    duration_min = duration_s / 60.0 if duration_s else 0.0
    zone_counts: dict[str, int] = {zone: 0 for zone in ("z1", "z2", "z3", "z4", "z5")}
    for bpm in heart_rates:
        zone_counts[_hr_zone(bpm)] += 1
    zone_minutes = {
        zone: round(duration_min * count / len(heart_rates), 2)
        for zone, count in zone_counts.items()
        if count
    }
    sorted_hr = sorted(heart_rates)
    p90_index = min(len(sorted_hr) - 1, math.ceil(len(sorted_hr) * 0.9) - 1)
    return HeartRateSummary(
        sample_count=len(heart_rates),
        avg_bpm=round(sum(heart_rates) / len(heart_rates), 1),
        p90_bpm=float(sorted_hr[p90_index]),
        zone_minutes=zone_minutes,
        samples=[],
    )


def _hr_zone(bpm: int) -> str:
    if bpm < 110:
        return "z1"
    if bpm < 130:
        return "z2"
    if bpm < 150:
        return "z3"
    if bpm < 170:
        return "z4"
    return "z5"


def _distance_m(points: list[dict[str, Any]]) -> float:
    distance = 0.0
    for previous, current in zip(points, points[1:]):
        distance += _haversine_m(previous["lat"], previous["lon"], current["lat"], current["lon"])
    return distance


def _ascent_descent(elevations: list[float]) -> tuple[float, float]:
    ascent = 0.0
    descent = 0.0
    for previous, current in zip(elevations, elevations[1:]):
        delta = current - previous
        if delta > 0:
            ascent += delta
        elif delta < 0:
            descent += abs(delta)
    return ascent, descent


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _find_int_child(element: ElementTree.Element, local_name: str) -> int | None:
    text = _descendant_text(element, local_name)
    return int(text) if text and re.match(r"^\d+$", text.strip()) else None


def _child_text(element: ElementTree.Element, local_name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == local_name:
            return child.text.strip() if child.text else None
    return None


def _descendant_text(element: ElementTree.Element, local_name: str) -> str | None:
    for child in element.iter():
        if _local_name(child.tag) == local_name and child.text:
            return child.text.strip()
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _activity_slug(activity_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", activity_id).strip("._")
    return slug or "activity"
