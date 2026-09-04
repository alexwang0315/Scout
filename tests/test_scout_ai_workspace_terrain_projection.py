from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scout.nextgen.workspace_terrain_projection import (
    build_workspace_terrain_projection,
    verify_projection_sources,
)


def test_selection_qualification_contexts_are_separate_and_gold_is_not_model_input(terrain_sources):
    from scout.nextgen.claim_selection_qualification import (
        build_scenario_request, qualification_catalog, qualification_scenarios,
    )
    from scout.nextgen.claim_support import claim_selection_prompt

    projection = build_workspace_terrain_projection(*terrain_sources)
    original = projection.model_dump_json()
    scenarios = qualification_scenarios()
    assert len(scenarios) == 13
    assert {case.mode for case in scenarios} == {"full", "missing", "stale", "conflicted", "none"}
    hashes = set()
    for scenario in scenarios:
        request = build_scenario_request(projection, scenario)
        hashes.add(request.workspace_binding.input_hash)
        prompt = claim_selection_prompt(request.question, request.claim_support)
        assert "expected_claim_ids" not in prompt and "expected_abstentions" not in prompt
        assert request.max_model_requests == request.capability_grant.max_tool_calls == 10
        assert request.allow_cloud_escalation is False
        for claim in projection.build_claim_support().claims:
            assert claim.statement not in prompt
        changed_gold = scenario.model_copy(update={"expected_claim_ids": (), "expected_abstentions": ()})
        assert build_scenario_request(projection, changed_gold).workspace_binding == request.workspace_binding
        if scenario.mode == "none":
            assert not request.evidence_refs and not request.claim_support.evidence and not request.claim_support.claims
    assert len(hashes) == len(scenarios)
    synthetic = qualification_catalog(projection).items[-1]
    assert "synthetic" in synthetic.source_type and "SYNTHETIC" in synthetic.summary
    assert synthetic.attributes["synthetic"] is True and synthetic.observed_at is None
    assert projection.model_dump_json() == original
    verify_projection_sources(projection)


@pytest.mark.parametrize("output_mode", ["full_report", "compact_advisory"])
def test_selection_modes_round_trip_through_praison_and_pydantic_replay(terrain_sources, output_mode):
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from scout.nextgen.claim_selection_qualification import (
        build_scenario_request, expected_selection_for_replay, qualification_catalog,
        qualification_scenarios, score_scenario_response,
    )
    from scout.nextgen.model_gateway import PydanticAIStructuredBackend, ScoutModelGateway
    from scout.nextgen.openai_compatible_backend import OpenAICompatibleBackendConfig
    from scout.nextgen.praison_service import PraisonIntelligenceService, PraisonModelGatewayRuntime

    projection = build_workspace_terrain_projection(*terrain_sources)
    catalog = qualification_catalog(projection)
    config = OpenAICompatibleBackendConfig(
        runtime_id="test.claim.modes", model_id="controlled-function-replay", provider="function-replay",
        base_url="http://127.0.0.1:1/v1", transport_scope="loopback", tier="local_fast",
        locality="edge", context_limit_tokens=8192, offline_capable=True, privacy_preserving=True,
    )
    for scenario in qualification_scenarios():
        request = build_scenario_request(projection, scenario)
        expected = expected_selection_for_replay(scenario, request)
        model_output = ({"claim_ids": [item.claim_id for item in (*expected.selections, *expected.abstentions)
                                     if item.claim_id != "uncovered_query"]}
                        if output_mode == "compact_advisory" else expected.model_dump(mode="json"))

        def model(messages, info, model_output=model_output):
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, model_output)])

        backend = PydanticAIStructuredBackend(
            runtime_id=config.runtime_id, model_id=config.model_id,
            model=FunctionModel(model, model_name=config.model_id),
        )
        with ScoutModelGateway(profiles=(config.to_runtime_profile(),), backends=(backend,)) as gateway:
            response = PraisonIntelligenceService(
                runtime=PraisonModelGatewayRuntime(gateway=gateway, specialist_output_mode=output_mode), evidence_catalog=catalog,
            ).execute(request)
        score = score_scenario_response(scenario, request, response)
        assert score["passed"], score
        assert score["model_request_count"] == (0 if scenario.mode == "none" else 1)
        if scenario.mode == "none":
            assert score["model_behavior_passed"] is None and score["deterministic_no_context_passed"]
        elif output_mode == "compact_advisory":
            assert score["model_responsibility"] == "subject_relevance_only"
        assert score["model_authored_prose_qualified"] is False
        if scenario.mode == "conflicted":
            assert len(response.conflicts) == 1 and response.conflicts[0].unresolved
        stale = request.workspace_binding.model_copy(update={"input_hash": "different_context"})
        assert not score_scenario_response(scenario, request, response, current_binding=stale)["passed"]


def test_valid_irrelevant_facts_and_deterministic_fallback_are_not_quality_passes(terrain_sources):
    from datetime import UTC, datetime
    from uuid import uuid4
    from scout.nextgen.claim_selection_qualification import build_scenario_request, qualification_scenarios, score_scenario_response
    from scout.nextgen.claim_support import render_supported_claim
    from scout.nextgen.praison_service import SpecialistReport
    from scout.nextgen.intelligence_gateway import (
        Finding, IntelligenceProvenance, IntelligenceResponse, ModelExecutionRecord, seal_intelligence_response,
    )

    projection = build_workspace_terrain_projection(*terrain_sources)
    scenario = qualification_scenarios()[0]
    request = build_scenario_request(projection, scenario)
    now = datetime.now(UTC)
    response = seal_intelligence_response(IntelligenceResponse(
        request_id=request.request_id,
        findings=tuple(Finding.model_validate(render_supported_claim(claim)) for claim in request.claim_support.claims),
        evidence=tuple(item.as_candidate_evidence() for item in projection.evidence_catalog.items),
        uncertainties=SpecialistReport.from_catalog_item(role="qgis", item=projection.evidence_catalog.items[-1]).uncertainties,
        provenance=IntelligenceProvenance(
            request_id=request.request_id, service_name="test", service_version="test",
            capability_grant_id=request.capability_grant.grant_id, workspace_binding=request.workspace_binding,
            output_hash="pending", model_runtimes=("test",), model_execution_records=(ModelExecutionRecord(
                parent_request_id=request.request_id, inference_id=uuid4(),
                runtime_id="test", model_id="fixture", locality="edge", started_at=now, completed_at=now,
                latency_ms=0, model_request_count=1, status="completed",
            ),),
        ),
    ))
    score = score_scenario_response(scenario, request, response)
    assert score["contract_accepted"] and not score["selection_matches"] and not score["passed"]
    fallback = response.model_copy(update={
        "findings": response.findings[:1],
        "provenance": response.provenance.model_copy(update={"model_execution_records": ()}),
    })
    assert not score_scenario_response(scenario, request, seal_intelligence_response(fallback))["passed"]


def test_no_context_score_rejects_forged_safety_text_under_correct_uncertainty_id(terrain_sources):
    from scout.nextgen.claim_selection_qualification import build_scenario_request, qualification_scenarios, score_scenario_response
    from scout.nextgen.intelligence_gateway import degraded_intelligence_response, seal_intelligence_response

    projection = build_workspace_terrain_projection(*terrain_sources)
    scenario = next(case for case in qualification_scenarios() if case.mode == "none")
    request = build_scenario_request(projection, scenario)
    response = degraded_intelligence_response(
        request=request, uncertainty_id="intelligence_evidence_unavailable", description="No evidence",
        missing_evidence=(), impact="UNKNOWN", service_name="test", service_version="test", agent_path=("degraded",),
    )
    assert score_scenario_response(scenario, request, response)["deterministic_no_context_passed"]
    forged = response.model_copy(update={"uncertainties": (response.uncertainties[0].model_copy(update={
        "description": "Verified safe trail; GO", "impact": "KNOWN",
    }),)})
    assert not score_scenario_response(scenario, request, seal_intelligence_response(forged))["passed"]


def test_cloud_comparison_requires_frozen_inputs_and_explicit_authorization(terrain_sources, tmp_path):
    from scout.nextgen.claim_selection_comparison import authorize_frozen_comparison
    from scout.nextgen.claim_selection_qualification import build_scenario_request, qualification_scenarios

    projection = build_workspace_terrain_projection(*terrain_sources)
    scenarios = qualification_scenarios()
    baseline = tmp_path / "baseline"
    _write_json(baseline / "case-definitions.json", {
        "scenarios": [case.model_dump(mode="json") for case in scenarios],
    })
    for scenario in scenarios:
        request = build_scenario_request(projection, scenario)
        _write_json(baseline / f"{scenario.case_id}.request.json", request.model_dump(mode="json"))
        fresh = build_scenario_request(projection, scenario)
        assert fresh.request_id != request.request_id
        with pytest.raises(ValueError, match="authorization"):
            authorize_frozen_comparison(fresh, case_id=scenario.case_id, baseline_dir=baseline, cloud_authorized=False)
        reviewed, audit = authorize_frozen_comparison(
            fresh, case_id=scenario.case_id, baseline_dir=baseline, cloud_authorized=True,
        )
        assert reviewed.allow_cloud_escalation and not reviewed.privacy_sensitive
        assert fresh.privacy_sensitive and not fresh.allow_cloud_escalation
        assert reviewed.workspace_binding == request.workspace_binding
        assert reviewed.capability_grant == fresh.capability_grant
        assert reviewed.max_model_requests == reviewed.capability_grant.max_tool_calls == 10
        assert audit["planned_question_evidence_binding_and_schema_match"]
        assert not audit["source_ledger_forwarded_to_model"]
        assert not audit["expected_answers_forwarded_to_model"]

    changed = fresh.model_copy(update={"question": "new unreviewed question"})
    with pytest.raises(ValueError, match="identity"):
        authorize_frozen_comparison(changed, case_id=scenario.case_id, baseline_dir=baseline, cloud_authorized=True)
    changed = fresh.model_copy(update={"workspace_binding": fresh.workspace_binding.model_copy(update={"input_hash": "changed"})})
    with pytest.raises(ValueError, match="input changed"):
        authorize_frozen_comparison(changed, case_id=scenario.case_id, baseline_dir=baseline, cloud_authorized=True)
    definitions = json.loads((baseline / "case-definitions.json").read_bytes())
    definitions["scenarios"][0]["expected_claim_ids"] = []
    _write_json(baseline / "case-definitions.json", definitions)
    with pytest.raises(ValueError, match="expected outcomes changed"):
        authorize_frozen_comparison(fresh, case_id=scenario.case_id, baseline_dir=baseline, cloud_authorized=True)


@pytest.mark.parametrize("name,value", [
    ("precise_latitude", 24.123456),
    ("ridge_sample_count", "private-source-path"),
    ("source_generated_at", "private-source-path"),
])
def test_comparison_model_projection_rejects_unreviewed_fields(terrain_sources, name, value):
    from scout.nextgen.claim_selection_comparison import comparison_input_audit
    from scout.nextgen.claim_selection_qualification import build_scenario_request, qualification_scenarios
    from scout.nextgen.claim_support import ClaimFact

    projection = build_workspace_terrain_projection(*terrain_sources)
    request = build_scenario_request(projection, qualification_scenarios()[0])
    support = request.claim_support
    claim = support.claims[0].model_copy(update={"facts": (ClaimFact(name=name, value=value),)})
    changed = request.model_copy(update={"claim_support": support.model_copy(update={"claims": (claim,)})})
    with pytest.raises(ValueError):
        comparison_input_audit(changed)


@pytest.mark.parametrize("tamper_catalog,invalid_attempts", [(False, 0), (True, 0), (False, 9)])
def test_comparison_http_payload_omits_private_ledger_and_uses_same_subject_schema(terrain_sources, tmp_path, tamper_catalog, invalid_attempts, monkeypatch):
    import httpx
    from scout.nextgen.claim_comparison_transport import ClaimComparisonTransport
    from scout.nextgen.claim_selection_comparison import authorize_frozen_comparison
    from scout.nextgen.claim_selection_qualification import build_scenario_request, qualification_catalog, qualification_scenarios, score_scenario_response
    from scout.nextgen.claim_support import claim_subject_prompt
    from scout.nextgen.openai_compatible_backend import OpenAICompatibleBackendConfig, build_praison_openai_compatible_runtime
    from scout.nextgen.praison_service import PraisonIntelligenceService

    projection = build_workspace_terrain_projection(*terrain_sources)
    scenario = qualification_scenarios()[0]
    original = build_scenario_request(projection, scenario)
    baseline = tmp_path / "baseline"
    _write_json(baseline / "case-definitions.json", {
        "scenarios": [case.model_dump(mode="json") for case in qualification_scenarios()],
    })
    _write_json(baseline / f"{scenario.case_id}.request.json", original.model_dump(mode="json"))
    request, audit = authorize_frozen_comparison(
        original, case_id=scenario.case_id, baseline_dir=baseline, cloud_authorized=True,
    )
    observed = []

    async def handle(http_request):
        observed.append(json.loads(http_request.content))
        return httpx.Response(200, json={
            "id": "test-chat", "object": "chat.completion", "created": 1788400000,
            "model": "test-remote", "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{}' if len(observed) <= invalid_attempts else '{"claim_ids":["ridge_samples"]}',
            }}], "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
        })

    config = OpenAICompatibleBackendConfig(
        runtime_id="test.cloud.comparison", provider="test-cloud", model_id="test-remote",
        base_url="https://models.example/v1", transport_scope="remote_https", tier="cloud_reasoning",
        locality="cloud", context_limit_tokens=8192, api_key_env="SCOUT_TEST_API_KEY",
        structured_output_mode="native", specialist_output_mode="compact_advisory",
        native_retry_context_mode="fresh_attempt",
    )
    audit_dir = tmp_path / "egress"
    attempted_shapes = []

    class ObservedTransport(ClaimComparisonTransport):
        async def handle_async_request(self, http_request):
            body = json.loads(await http_request.aread())
            attempted_shapes.append({"fields": sorted(body), "response_format": body.get("response_format"),
                                     "messages": body.get("messages")})
            return await super().handle_async_request(http_request)

    transport = ObservedTransport(
        review={"cases": [audit]}, config=config, audit_dir=audit_dir, inner=httpx.MockTransport(handle),
    )
    runtime = build_praison_openai_compatible_runtime(
        config=config, environ={"SCOUT_TEST_API_KEY": "test-only-placeholder"},
        http_client=httpx.AsyncClient(transport=transport, trust_env=False),
    )
    catalog = qualification_catalog(projection)
    if tamper_catalog:
        catalog = catalog.model_copy(update={"items": tuple(
            item.model_copy(update={"attributes": {}}) if item.evidence_id == "workspace-qgis" else item
            for item in catalog.items
        )})
    try:
        response = PraisonIntelligenceService(runtime=runtime, evidence_catalog=catalog).execute(request)
    finally:
        runtime.close()
    audit_records = [json.loads(path.read_bytes()) for path in audit_dir.glob("*.json")]
    if tamper_catalog:
        assert any(item["status"] == "rejected_before_network" for item in audit_records), response
        assert not score_scenario_response(scenario, request, response)["passed"]
    else:
        assert score_scenario_response(scenario, request, response)["passed"], json.dumps({"audit": audit_records, "attempted": attempted_shapes})
    assert len(observed) == invalid_attempts + 1
    body = observed[0]
    assert body["model"] == config.model_id
    assert [message["content"] for message in body["messages"] if message["role"] == "user"] == [
        claim_subject_prompt(request.question, request.claim_support),
    ]
    encoded = json.dumps(body)
    for private in (request.mission_id, str(request.request_id), *request.evidence_refs):
        assert private not in encoded
    assert "structured_input" not in body and "expected_claim_ids" not in encoded
    assert set(body["response_format"]["json_schema"]["schema"]["properties"]) == {"claim_ids"}
    if not tamper_catalog:
        from scout.nextgen.claim_comparison_report import verify_case_egress

        kwargs = dict(case_id=scenario.case_id, response=response, audit=audit, records=audit_records,
                      config=config, expects_model=True)
        assert verify_case_egress(**kwargs)
        for field, value in (("observed_model", "wrong-model"), ("model_prompt_sha256", "wrong-prompt"),
                             ("wire_output_schema_sha256", "wrong-schema"), ("body_sha256", "wrong-body")):
            wrong = [dict(item, **{field: value}) if item["status"] == "response_received" else item for item in audit_records]
            assert not verify_case_egress(**{**kwargs, "records": wrong})
        assert not verify_case_egress(**{**kwargs, "records": audit_records[:-1]})
        wrong = response.model_copy(update={"provenance": response.provenance.model_copy(update={"agent_path": ("terrain.full_report",)})})
        assert not verify_case_egress(**{**kwargs, "response": wrong})
        from datetime import datetime, timedelta
        from uuid import uuid4

        shifted = [{**item, **{key: (datetime.fromisoformat(item[key]) + timedelta(days=365)).isoformat()
                               for key in ("started_at", "completed_at") if key in item}}
                   for item in audit_records]
        assert not verify_case_egress(**{**kwargs, "records": shifted})
        for field, value in (("parent_request_id", uuid4()), ("inference_id", None)):
            execution = response.provenance.model_execution_records[0].model_copy(update={field: value})
            wrong = response.model_copy(update={"provenance": response.provenance.model_copy(update={
                "model_execution_records": (execution,),
            })})
            assert not verify_case_egress(**{**kwargs, "response": wrong})
        if invalid_attempts == 0:
            _assert_comparison_report_rejects_duplicate_cases_and_replays_history(
                monkeypatch, tmp_path, scenario, request, response, baseline, audit_dir, config,
            )


def _assert_comparison_report_rejects_duplicate_cases_and_replays_history(
    monkeypatch, tmp_path, scenario, request, response, baseline, audit_dir, config,
):
    from datetime import UTC, datetime, timedelta
    import scout.nextgen.claim_comparison_report as report_module
    import scout.nextgen.claim_selection_comparison as comparison_module
    import scout.nextgen.intelligence_gateway as gateway_module
    from scout.nextgen.claim_selection_qualification import score_scenario_response
    from scout.nextgen.intelligence_gateway import intelligence_response_hash

    monkeypatch.setattr(report_module, "qualification_scenarios", lambda: (scenario,))
    monkeypatch.setattr(comparison_module, "qualification_scenarios", lambda: (scenario,))
    _write_json(baseline / "case-definitions.json", {"scenarios": [scenario.model_dump(mode="json")]})
    score = score_scenario_response(scenario, request, response)
    summary = {"cases": [score], "model_case_count": 1, "model_behavior_passed_count": 1,
               "model_request_count": 1, "elapsed_seconds_total": 1}
    receipt = {"response": response.model_dump(mode="json"), "output_hash": intelligence_response_hash(response),
               "request_id": str(request.request_id), "case": scenario.model_dump(mode="json"),
               "final_state": "completed", "error_type": None, "elapsed_seconds": 1}
    results = tmp_path / "report-results"
    for directory in (baseline, results):
        _write_json(directory / "qualification.json", summary)
        _write_json(directory / f"{scenario.case_id}.request.json", request.model_dump(mode="json"))
        _write_json(directory / f"{scenario.case_id}.json", receipt)
    kwargs = dict(baseline_dir=baseline, result_dir=results, egress_dir=audit_dir, config=config)
    report = report_module.build_comparison_report(**kwargs)
    assert report["comparison_valid"] and report["current_model_passed"] == report["current_model_cases"] == 1
    for directory in (baseline, results):
        _write_json(directory / "qualification.json", {**summary, "cases": [score, score]})
        with pytest.raises(ValueError, match="duplicate"):
            report_module.build_comparison_report(**kwargs)
        _write_json(directory / "qualification.json", summary)

    class FutureDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return (request.capability_grant.expires_at + timedelta(days=365)).astimezone(tz or UTC)

    monkeypatch.setattr(gateway_module, "datetime", FutureDatetime)
    assert not score_scenario_response(scenario, request, response)["contract_accepted"]
    historical = report_module.build_comparison_report(**kwargs)
    assert historical["comparison_valid"] and historical["checks"] == report["checks"]
    assert historical["baseline_model_passed"] == report["baseline_model_passed"]
    assert historical["scoring_time_basis"] == "verified_response_generated_at"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def terrain_sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "workspace"
    run = root / "outputs/spatial/qgis/run-1"
    route = root / "normalized/routes/filtered/route.gpx"
    route.parent.mkdir(parents=True)
    route.write_bytes(b"<gpx><trk/></gpx>")
    dem = tmp_path / "prepared-dem.tif"
    dem.write_bytes(b"test DEM hash binding, not a real raster")
    _write_json(root / "project.json", {
        "project_id": "test-workspace", "route_name": "Test Route",
        "route_evidence_bundle_ref": "normalized/routes/route_evidence_bundle.json",
    })
    _write_json(root / "normalized/routes/route_evidence_bundle.json", {
        "golden_route": {"filtered_geometry_ref": str(route.relative_to(root))},
    })
    boundary = {"candidate_only": True, "operational": False,
                "runtime_safety_truth": False, "adds_source_resolution": False}
    manifest = {
        **boundary, "workflow_id": "terrain_feature_stack.v1", "workflow_run_id": "run-1",
        "source_crs": "EPSG:3826", "source_resolution": {"x_m": 20, "y_m": 20},
        "source_hashes": {"/state/route.gpx": _hash(route), "/state/dem.tif": _hash(dem)},
        "source_dem_inspection": {"summary": {"source": "/state/dem.tif"}},
        "artifacts": {"route_feature_samples": "terrain_feature_route_samples.geojson"},
        "parameters": {"route_export_file_crs": "UNKNOWN"},
    }
    _write_json(run / "terrain_feature_manifest.json", manifest)
    features = [{"type": "Feature", "properties": {
        **boundary, "fixture": False, "synthetic": False, "workflow_run_id": "run-1",
        "sample_id": f"sample-{index}", "slope_degrees": slope,
        "geomorphon_consensus_code": code,
    }} for index, (slope, code) in enumerate([(16.0, 3), (35.0, 6), (45.0, 3), (None, None)])]
    _write_json(run / "terrain_feature_route_samples.geojson", {
        "type": "FeatureCollection", "metadata": {**boundary, "workflow_run_id": "run-1",
        "sample_count": 4, "source_route_coordinate_count": 40}, "features": features,
    })
    artifacts = [{**boundary, "fixture": False, "synthetic": False,
                  "artifact_ref": str(path.relative_to(root)), "artifact_hash": _hash(path)}
                 for path in (run / "terrain_feature_manifest.json",
                              run / "terrain_feature_route_samples.geojson")]
    _write_json(run / "workflow_run.json", {
        **boundary, "project_id": "test-workspace", "workflow_id": "terrain_feature_stack.v1",
        "workflow_run_id": "run-1", "state": "completed", "processing_status": "completed",
        "completed_at": "2026-08-23T08:17:55Z", "human_review_status": "pending",
        "machine_review_status": "not_started", "visual_review_status": "pending",
        "source_hashes": {str(route.relative_to(root)): _hash(route)}, "artifacts": artifacts,
    })
    return root, run.relative_to(root), dem


def test_projection_aggregates_real_bound_sources_without_workspace_writes(terrain_sources):
    root, run, dem = terrain_sources
    before = {str(p): _hash(p) for p in root.rglob("*") if p.is_file()}
    projection = build_workspace_terrain_projection(root, run, dem)
    assert projection.metrics.sample_count == 4
    assert projection.metrics.ridge_sample_count == 2
    assert projection.metrics.slope_ge_30_count == 2
    assert projection.metrics.slope_ge_40_count == 1
    assert projection.metrics.max_slope_degrees == 45
    assert projection.metrics.missing_slope_count == 1
    assert projection.metrics.missing_geomorphon_count == 1
    assert projection.saddle_status == "UNKNOWN"
    assert projection.field_conditions_status == "UNKNOWN"
    assert projection.candidate_only and not projection.runtime_safety_truth
    assert {str(p): _hash(p) for p in root.rglob("*") if p.is_file()} == before
    assert verify_projection_sources(projection) == projection.workspace_binding
    request = projection.build_request()
    assert request.allow_cloud_escalation is False
    assert request.max_model_requests == 10
    assert request.workspace_binding == projection.workspace_binding
    assert "web.search" not in request.capability_grant.allowed_capabilities
    assert request.request_id != projection.build_request().request_id
    assert all(item.observed_at is None for item in projection.evidence_catalog.items)
    assert projection.evidence_catalog.items[0].resolution is None
    assert any("historical" in item.summary.lower() for item in projection.evidence_catalog.items)


@pytest.mark.parametrize("target", ["dem", "route", "samples"])
def test_projection_rejects_changed_hash(terrain_sources, target):
    root, run, dem = terrain_sources
    path = {"dem": dem, "route": root / "normalized/routes/filtered/route.gpx",
            "samples": root / run / "terrain_feature_route_samples.geojson"}[target]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash"):
        build_workspace_terrain_projection(root, run, dem)


def test_projection_revalidation_rejects_workspace_change(terrain_sources):
    root, run, dem = terrain_sources
    projection = build_workspace_terrain_projection(root, run, dem)
    _write_json(root / "project.json", {"project_id": "changed-mission"})
    with pytest.raises(ValueError, match="stale"):
        verify_projection_sources(projection)


def test_projection_revalidation_rejects_changed_derived_metrics(terrain_sources):
    root, run, dem = terrain_sources
    projection = build_workspace_terrain_projection(root, run, dem)
    changed = projection.model_copy(update={
        "metrics": projection.metrics.model_copy(update={"ridge_sample_count": 3}),
    })
    with pytest.raises(ValueError, match="stale"):
        verify_projection_sources(changed)


def test_projection_rejects_route_path_escape(terrain_sources):
    root, run, dem = terrain_sources
    _write_json(root / "normalized/routes/route_evidence_bundle.json", {
        "golden_route": {"filtered_geometry_ref": "../../private.gpx"},
    })
    with pytest.raises(ValueError, match="outside workspace"):
        build_workspace_terrain_projection(root, run, dem)


@pytest.mark.parametrize("change", [
    {"runtime_safety_truth": True}, {"fixture": True}, {"synthetic": True},
    {"workflow_run_id": "other-run"}, {"slope_degrees": float("nan")},
])
def test_projection_rejects_invalid_or_promoted_samples(terrain_sources, change):
    root, run, dem = terrain_sources
    path = root / run / "terrain_feature_route_samples.geojson"
    data = json.loads(path.read_text())
    data["features"][0]["properties"].update(change)
    _write_json(path, data)
    workflow_path = root / run / "workflow_run.json"
    workflow = json.loads(workflow_path.read_text())
    workflow["artifacts"][1]["artifact_hash"] = _hash(path)
    _write_json(workflow_path, workflow)
    with pytest.raises(ValueError):
        build_workspace_terrain_projection(root, run, dem)
