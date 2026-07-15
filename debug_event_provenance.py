from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


PROVENANCE_CONTRACT_VERSION = "scout.debug.event-provenance.v1"


class DebugEventProvenance(str, Enum):
    RUNTIME = "runtime"
    FIXTURE_REPLAY = "fixture_replay"
    SMOKE = "smoke"
    HISTORICAL = "historical"
    PROJECTION = "projection"
    UNKNOWN = "unknown"


class DebugEventIngestionChannel(str, Enum):
    RUNTIME_LOG = "runtime_log"
    FIXTURE_REPLAY = "fixture_replay"
    SMOKE_HARNESS = "smoke_harness"
    HISTORICAL_ARCHIVE = "historical_archive"
    PRETRIP_PROJECTION = "pretrip_projection"


_PROVENANCE_BY_CHANNEL: Mapping[
    DebugEventIngestionChannel, DebugEventProvenance
] = {
    DebugEventIngestionChannel.RUNTIME_LOG: DebugEventProvenance.RUNTIME,
    DebugEventIngestionChannel.FIXTURE_REPLAY: DebugEventProvenance.FIXTURE_REPLAY,
    DebugEventIngestionChannel.SMOKE_HARNESS: DebugEventProvenance.SMOKE,
    DebugEventIngestionChannel.HISTORICAL_ARCHIVE: DebugEventProvenance.HISTORICAL,
    DebugEventIngestionChannel.PRETRIP_PROJECTION: DebugEventProvenance.PROJECTION,
}


def debug_event_provenance_contract() -> dict[str, Any]:
    return {
        "version": PROVENANCE_CONTRACT_VERSION,
        "authoritative": True,
        "authority": "server_ingestion_channel",
        "unknown_by_default": True,
        "transport_independent": True,
        "payload_claims_ignored": True,
        "allowed_values": [item.value for item in DebugEventProvenance],
    }


def stamp_debug_event(
    event: Any,
    *,
    ingestion_channel: DebugEventIngestionChannel | Any,
) -> dict[str, Any]:
    """Return a new event stamped only by a trusted server-owned channel."""

    if hasattr(event, "model_dump"):
        event_payload = event.model_dump(mode="json")
    else:
        event_payload = dict(event)
    provenance = (
        _PROVENANCE_BY_CHANNEL.get(ingestion_channel, DebugEventProvenance.UNKNOWN)
        if isinstance(ingestion_channel, DebugEventIngestionChannel)
        else DebugEventProvenance.UNKNOWN
    )
    provenance_contract = event_payload.get("provenance_contract")
    already_authoritative = (
        isinstance(provenance_contract, Mapping)
        and provenance_contract.get("version") == PROVENANCE_CONTRACT_VERSION
        and provenance_contract.get("authoritative") is True
    )
    nested_payload = event_payload.get("payload")
    nested_claim = isinstance(nested_payload, Mapping) and any(
        key in nested_payload for key in ("event_provenance", "provenance")
    )
    payload_claims_ignored = nested_claim or (
        not already_authoritative
        and any(key in event_payload for key in ("event_provenance", "provenance"))
    )
    channel_name = (
        ingestion_channel.value
        if isinstance(ingestion_channel, DebugEventIngestionChannel)
        else "unknown"
    )
    return {
        **event_payload,
        "event_provenance": provenance.value,
        "provenance_contract": {
            "version": PROVENANCE_CONTRACT_VERSION,
            "authoritative": True,
            "ingestion_channel": channel_name,
            "payload_claims_ignored": payload_claims_ignored,
        },
    }


def stamp_debug_events(
    events: list[Any],
    *,
    ingestion_channel: DebugEventIngestionChannel | Any,
) -> list[dict[str, Any]]:
    return [
        stamp_debug_event(event, ingestion_channel=ingestion_channel)
        for event in events
    ]
