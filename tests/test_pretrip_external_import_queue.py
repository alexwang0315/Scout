import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_external_import_queue
from pretrip_external_import_queue import (
    ExternalImportQueue,
    build_chilai_external_import_queue,
    external_import_queue_to_json,
    load_external_import_queue,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "outputs"
    / "external_import_queue.json"
)


def test_builds_chilai_external_import_queue_as_reference_only_artifact_requests():
    queue = build_chilai_external_import_queue()
    payload = queue.model_dump(mode="json")

    assert payload["queue_id"] == "external_import_queue.chilai_nanhua_day1.v0"
    assert payload["artifact_kind"] == "pretrip_external_import_queue"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["status"] == "pending_human_review"
    assert payload["counts"] == {
        "request_count": 3,
        "pending_count": 3,
        "crawler_enabled_count": 0,
        "network_call_count": 0,
        "observed_fact_count": 0,
        "raw_payloads_embedded": False,
    }

    by_source_id = {request["source_id"]: request for request in payload["requests"]}
    assert set(by_source_id) == {
        "source.joyhike.main_site",
        "source.joyhike.blog",
        "source.ptt.sunriver_timing",
    }
    assert by_source_id["source.joyhike.main_site"]["source_url"] == "https://joyhike.com/"
    assert (
        by_source_id["source.joyhike.blog"]["source_url"]
        == "https://blog.joyhike.com/2022/05/trailslevel.html"
    )
    assert (
        by_source_id["source.ptt.sunriver_timing"]["source_url"]
        == "https://www.ptt.cc/bbs/Hiking/M.1696430399.A.151.html"
    )

    assert all(request["requested_artifact_kind"] == "planning_reference" for request in payload["requests"])
    assert all(request["review_requirement"] == "human_review_required" for request in payload["requests"])
    assert all(request["crawler_enabled"] is False for request in payload["requests"])
    assert all(request["network_call_count"] == 0 for request in payload["requests"])
    assert all(request["raw_payload_embedded"] is False for request in payload["requests"])
    assert all(request["observed_fact_candidate"] is False for request in payload["requests"])
    assert all(request["derived_measurement_candidate"] is False for request in payload["requests"])
    assert all(request["authoritative_until_reviewed"] is False for request in payload["requests"])
    assert all(
        request["intended_treatment"]
        == ["planning_reference", "model_interpretation_input", "human_review_required"]
        for request in payload["requests"]
    )


def test_external_import_queue_has_no_network_crawler_or_import_side_effects():
    queue = build_chilai_external_import_queue()
    serialized = external_import_queue_to_json(queue)

    for forbidden_fragment in [
        "ObservedFact",
        "DerivedMeasurement",
        "raw_html",
        "snapshot_body",
        "raw_payload_embedded\": true",
        "raw_payloads_embedded\": true",
        "crawler_enabled\": true",
        "network_call_count\": 1",
    ]:
        assert forbidden_fragment not in serialized

    source = inspect.getsource(pretrip_external_import_queue)
    for forbidden_source in [
        "requests.",
        "httpx.",
        "urllib.request",
        "urlopen",
        "BeautifulSoup",
        "selenium",
        "playwright",
        "subprocess",
        "socket.",
        "from pretrip_source_ingest",
        "ingest_source_artifact",
    ]:
        assert forbidden_source not in source


def test_external_import_queue_fixture_matches_builder_output():
    fixture_payload = FIXTURE_PATH.read_text(encoding="utf-8")
    fixture = load_external_import_queue(FIXTURE_PATH)
    regenerated = build_chilai_external_import_queue()

    assert fixture == regenerated
    assert fixture_payload == external_import_queue_to_json(regenerated)


def test_external_import_queue_schema_rejects_crawler_network_and_payload_claims():
    payload = build_chilai_external_import_queue().model_dump(mode="json")
    payload["requests"][0]["crawler_enabled"] = True
    with pytest.raises(ValidationError):
        ExternalImportQueue.model_validate(payload)

    payload = build_chilai_external_import_queue().model_dump(mode="json")
    payload["requests"][0]["network_call_count"] = 1
    with pytest.raises(ValidationError):
        ExternalImportQueue.model_validate(payload)

    payload = build_chilai_external_import_queue().model_dump(mode="json")
    payload["requests"][0]["raw_payload_embedded"] = True
    with pytest.raises(ValidationError):
        ExternalImportQueue.model_validate(payload)

    payload = build_chilai_external_import_queue().model_dump(mode="json")
    payload["requests"][0]["observed_fact_candidate"] = True
    with pytest.raises(ValidationError):
        ExternalImportQueue.model_validate(payload)

    payload = build_chilai_external_import_queue().model_dump(mode="json")
    payload["counts"]["network_call_count"] = 1
    with pytest.raises(ValidationError):
        ExternalImportQueue.model_validate(payload)
