from debug_event_provenance import (
    DebugEventIngestionChannel,
    stamp_debug_event,
)


def test_trusted_ingestion_channel_owns_event_provenance_without_mutating_input() -> None:
    event = {
        "event_id": "debug_event.fixture.spoof",
        "event_provenance": "runtime",
        "summary": "Claims live runtime in display text",
        "transport": "connected",
        "payload": {
            "event_provenance": "runtime",
            "provenance": "live",
        },
    }

    stamped = stamp_debug_event(
        event,
        ingestion_channel=DebugEventIngestionChannel.FIXTURE_REPLAY,
    )

    assert event["event_provenance"] == "runtime"
    assert stamped["event_provenance"] == "fixture_replay"
    assert stamped["provenance_contract"] == {
        "version": "scout.debug.event-provenance.v1",
        "authoritative": True,
        "ingestion_channel": "fixture_replay",
        "payload_claims_ignored": True,
    }


def test_all_trusted_channels_and_unknown_fail_closed_are_stable_on_rehydration() -> None:
    cases = [
        (DebugEventIngestionChannel.RUNTIME_LOG, "runtime"),
        (DebugEventIngestionChannel.FIXTURE_REPLAY, "fixture_replay"),
        (DebugEventIngestionChannel.SMOKE_HARNESS, "smoke"),
        (DebugEventIngestionChannel.HISTORICAL_ARCHIVE, "historical"),
        (DebugEventIngestionChannel.PRETRIP_PROJECTION, "projection"),
        (None, "unknown"),
        ("runtime_log", "unknown"),
    ]

    for ingestion_channel, expected in cases:
        first = stamp_debug_event(
            {"event_id": f"debug_event.{expected}", "payload": {"event_provenance": "runtime"}},
            ingestion_channel=ingestion_channel,
        )
        second = stamp_debug_event(first, ingestion_channel=ingestion_channel)

        assert first["event_provenance"] == expected
        assert second["event_provenance"] == expected
        assert second["provenance_contract"] == first["provenance_contract"]
