import inspect
from pathlib import Path

from runtime_activation_loader import (
    DEFAULT_RUNTIME_ACTIVATION_BLOCKED_REPORT_NAME,
    DEFAULT_RUNTIME_ACTIVATION_RECORD_DIR,
    DEFAULT_RUNTIME_OBSERVATION_BATCH_RECORD_DIR,
    DEFAULT_RUNTIME_LIFECYCLE_RECORD_DIR,
    DEFAULT_RUNTIME_OBSERVATION_START_RECORD_DIR,
    DEFAULT_RUNTIME_STREAM_GUARD_RECORD_DIR,
    RuntimeLifecycleAction,
    RuntimeActivationLoaderStatus,
    activate_runtime_export,
    apply_runtime_lifecycle_control,
    load_runtime_activation_blocked_report,
    load_runtime_activation_record,
    load_runtime_lifecycle_control_record,
    load_runtime_observation_batch_record,
    load_runtime_observation_start_record,
    load_runtime_stream_guard_record,
    process_runtime_observation_batch,
    request_runtime_stream_start,
    start_runtime_observing,
)
from safety_models import Observation
from tests.test_runtime_load_dry_run import _runtime_export_with_activation_request


def test_runtime_activation_loader_creates_loaded_not_observing_session(tmp_path):
    workspace_root, export_root = _runtime_export_with_activation_request(tmp_path)
    state_root = tmp_path / "runtime_state"

    result = activate_runtime_export(
        export_root,
        state_root,
        activation_id="activation.chilai_nanhua_day1.quick_review.v0",
        activated_by="operator:alex",
        activated_at="2026-05-18T10:00:00+08:00",
        activation_reason="Operator starts Phase 1 runtime session from reviewed export.",
    )

    assert result.status == RuntimeActivationLoaderStatus.LOADED_NOT_OBSERVING
    assert result.blocked_report is None
    assert result.activation_record is not None
    assert result.session is not None

    snapshot = result.session.snapshot()
    assert snapshot.observations_processed == 0
    assert snapshot.incident_packages == []
    assert snapshot.stored_incident_paths == []
    assert result.session.incident_bridge is None

    record = result.activation_record
    assert record.status == RuntimeActivationLoaderStatus.LOADED_NOT_OBSERVING
    assert record.activation_performed is True
    assert record.project_id == "chilai_nanhua_day1"
    assert record.export_id == "runtime_export.chilai_nanhua_day1.quick_review.v0"
    assert record.request_id == "runtime_activation_request.chilai_nanhua_day1.quick_review.v0"
    assert record.route_source_ref == "artifact:gpx:chilai_nanhua_day1"
    assert record.route_artifact_runtime_ref == "route_artifacts/chilai_nanhua_day1.gpx"
    assert record.route_point_count == 2
    assert record.counts.model_dump(mode="json") == {
        "runtime_activation_attempt_count": 1,
        "runtime_activation_record_count": 1,
        "safety_runtime_session_count": 1,
        "observations_processed_count": 0,
        "incident_package_count": 0,
        "stored_incident_path_count": 0,
        "safety_api_call_count": 0,
        "phase2_writeback_count": 0,
        "raw_payload_copy_count": 0,
        "blocker_count": 0,
    }
    assert record.boundary.model_dump(mode="json") == {
        "phase1_runtime_loader": True,
        "creates_safety_runtime_session": True,
        "starts_observation_processing": False,
        "calls_safety_api": False,
        "writes_phase2_brain": False,
        "mutates_runtime_export": False,
        "mutates_activation_request": False,
        "incident_bridge_enabled": False,
        "raw_payloads_embedded": False,
        "activation_state": "loaded_not_observing",
        "notes": [
            "Actual Runtime Activation / 實際啟動現場 runtime loads the session only.",
            "The first implemented state is loaded_not_observing / 已載入未觀測.",
            "Observation processing, safety APIs, incident bridge, and Phase 2 writeback remain closed.",
        ],
    }

    record_path = (
        state_root
        / DEFAULT_RUNTIME_ACTIVATION_RECORD_DIR
        / "activation.chilai_nanhua_day1.quick_review.v0.json"
    )
    assert record_path.is_file()
    loaded_record = load_runtime_activation_record(record_path)
    assert loaded_record == record
    serialized = record.to_json()
    assert str(workspace_root) not in serialized
    assert str(export_root) not in serialized
    assert "/private/" not in serialized
    assert "<gpx" not in serialized


def test_runtime_activation_loader_blocks_duplicate_activation_id(tmp_path):
    _, export_root = _runtime_export_with_activation_request(tmp_path)
    state_root = tmp_path / "runtime_state"

    activate_runtime_export(
        export_root,
        state_root,
        activation_id="activation.chilai_nanhua_day1.quick_review.v0",
        activated_by="operator:alex",
        activated_at="2026-05-18T10:00:00+08:00",
        activation_reason="First activation.",
    )
    duplicate = activate_runtime_export(
        export_root,
        state_root,
        activation_id="activation.chilai_nanhua_day1.quick_review.v0",
        activated_by="operator:alex",
        activated_at="2026-05-18T10:05:00+08:00",
        activation_reason="Duplicate activation should be blocked.",
    )

    assert duplicate.status == RuntimeActivationLoaderStatus.ACTIVATION_BLOCKED
    assert duplicate.session is None
    assert duplicate.activation_record is None
    assert duplicate.blocked_report is not None
    assert duplicate.blocked_report.counts.safety_runtime_session_count == 0
    assert duplicate.blocked_report.counts.runtime_activation_record_count == 0
    assert [finding.finding_id for finding in duplicate.blocked_report.findings] == [
        "runtime_activation_record_exists"
    ]


def test_runtime_activation_loader_starts_observing_with_initial_observation(tmp_path):
    _, export_root = _runtime_export_with_activation_request(tmp_path)
    state_root = tmp_path / "runtime_state"
    activation = activate_runtime_export(
        export_root,
        state_root,
        activation_id="activation.chilai_nanhua_day1.quick_review.v0",
        activated_by="operator:alex",
        activated_at="2026-05-18T10:00:00+08:00",
        activation_reason="Operator starts Phase 1 runtime session from reviewed export.",
    )

    observing = start_runtime_observing(
        activation,
        state_root,
        Observation(
            timestamp=0.0,
            source="operator_initial_fix",
            lat=24.000000,
            lon=121.000000,
            elevation_m=1000.0,
            gps_horizontal_accuracy_m=8.0,
            raw={"sensorlog": {"loggingTime": "2026-05-08T00:00:00Z"}},
        ),
        observing_id="observing.chilai_nanhua_day1.quick_review.v0",
        started_by="operator:alex",
        started_at="2026-05-18T10:01:00+08:00",
        start_reason="Operator confirms first field observation.",
    )

    assert observing.status == RuntimeActivationLoaderStatus.OBSERVING
    assert observing.session is activation.session
    snapshot = observing.session.snapshot()
    assert snapshot.observations_processed == 1
    assert snapshot.incident_packages == []
    assert snapshot.stored_incident_paths == []

    record = observing.observation_start_record
    assert record.status == RuntimeActivationLoaderStatus.OBSERVING
    assert record.activation_status_before_start == "loaded_not_observing"
    assert record.activation_id == "activation.chilai_nanhua_day1.quick_review.v0"
    assert record.observation_source == "operator_initial_fix"
    assert record.observation_timestamp == 0.0
    assert record.route_progress_sample_available is True
    assert record.safety_state["level"] == "L0_NORMAL"
    assert record.safety_event_count == 0
    assert record.recording_policy_profile == "medium"
    assert record.counts.model_dump(mode="json") == {
        "runtime_activation_attempt_count": 1,
        "runtime_activation_record_count": 1,
        "safety_runtime_session_count": 1,
        "observations_processed_count": 1,
        "incident_package_count": 0,
        "stored_incident_path_count": 0,
        "safety_api_call_count": 0,
        "phase2_writeback_count": 0,
        "raw_payload_copy_count": 0,
        "blocker_count": 0,
    }
    assert record.boundary.model_dump(mode="json") == {
        "phase1_runtime_loader": True,
        "uses_existing_safety_runtime_session": True,
        "starts_observation_processing": True,
        "accepts_single_initial_observation": True,
        "calls_safety_api": False,
        "writes_phase2_brain": False,
        "mutates_runtime_export": False,
        "mutates_activation_request": False,
        "incident_bridge_enabled": False,
        "raw_observation_embedded": False,
        "activation_state": "observing",
        "notes": [
            "Observing / 現場觀測中 starts with one explicit initial observation.",
            "This slice does not connect a continuous sensor stream or HTTP safety API.",
            "Phase 2 writeback and incident bridge remain disabled.",
        ],
    }
    record_path = (
        state_root
        / DEFAULT_RUNTIME_OBSERVATION_START_RECORD_DIR
        / "observing.chilai_nanhua_day1.quick_review.v0.json"
    )
    assert load_runtime_observation_start_record(record_path) == record
    serialized = record.to_json()
    assert "operator_initial_fix" in serialized
    assert "sensorlog" not in serialized
    assert "<gpx" not in serialized
    assert "/private/" not in serialized


def test_runtime_activation_loader_rejects_observing_without_loaded_session(tmp_path):
    _, export_root = _runtime_export_with_activation_request(tmp_path)
    state_root = tmp_path / "runtime_state"
    activation = activate_runtime_export(
        export_root,
        state_root,
        activation_id="activation.chilai_nanhua_day1.quick_review.v0",
        activated_by="operator:alex",
        activated_at="2026-05-18T10:00:00+08:00",
        activation_reason="Operator starts Phase 1 runtime session from reviewed export.",
    )
    start_runtime_observing(
        activation,
        state_root,
        Observation(timestamp=0.0, source="operator_initial_fix", lat=24.0, lon=121.0),
        observing_id="observing.chilai_nanhua_day1.quick_review.v0",
        started_by="operator:alex",
        started_at="2026-05-18T10:01:00+08:00",
        start_reason="First observing start succeeds.",
    )

    try:
        start_runtime_observing(
            activation,
            state_root,
            Observation(timestamp=1.0, source="operator_initial_fix", lat=24.0, lon=121.0),
            observing_id="observing.chilai_nanhua_day1.quick_review.v0",
            started_by="operator:alex",
            started_at="2026-05-18T10:02:00+08:00",
            start_reason="Duplicate observing start should fail.",
        )
    except FileExistsError as exc:
        assert "runtime observation start record already exists" in str(exc)
    else:
        raise AssertionError("expected duplicate observing start rejection")


def test_runtime_lifecycle_controls_pause_resume_and_end_without_observation(tmp_path):
    state_root = tmp_path / "runtime_state"
    observing = _started_observing(tmp_path, state_root)

    paused = apply_runtime_lifecycle_control(
        observing,
        state_root,
        action=RuntimeLifecycleAction.PAUSE,
        control_id="lifecycle.pause.chilai_nanhua_day1.quick_review.v0",
        controlled_by="operator:alex",
        controlled_at="2026-05-18T10:02:00+08:00",
        control_reason="Operator pauses field observation.",
    )
    resumed = apply_runtime_lifecycle_control(
        paused,
        state_root,
        action=RuntimeLifecycleAction.RESUME,
        control_id="lifecycle.resume.chilai_nanhua_day1.quick_review.v0",
        controlled_by="operator:alex",
        controlled_at="2026-05-18T10:03:00+08:00",
        control_reason="Operator resumes field observation.",
    )
    ended = apply_runtime_lifecycle_control(
        resumed,
        state_root,
        action=RuntimeLifecycleAction.END,
        control_id="lifecycle.end.chilai_nanhua_day1.quick_review.v0",
        controlled_by="operator:alex",
        controlled_at="2026-05-18T10:04:00+08:00",
        control_reason="Operator ends the runtime session.",
    )

    assert paused.status == RuntimeActivationLoaderStatus.PAUSED
    assert resumed.status == RuntimeActivationLoaderStatus.OBSERVING
    assert ended.status == RuntimeActivationLoaderStatus.ENDED
    assert ended.lifecycle_record.terminal_state is True
    assert ended.session is observing.session
    assert ended.session.snapshot().observations_processed == 1

    assert paused.lifecycle_record.action == "pause"
    assert paused.lifecycle_record.previous_status == "observing"
    assert paused.lifecycle_record.status == "paused"
    assert paused.lifecycle_record.terminal_state is False
    assert paused.lifecycle_record.counts.observations_processed_count == 1
    assert paused.lifecycle_record.counts.incident_package_count == 0
    assert paused.lifecycle_record.counts.safety_api_call_count == 0
    assert paused.lifecycle_record.counts.phase2_writeback_count == 0
    assert paused.lifecycle_record.boundary.model_dump(mode="json") == {
        "phase1_runtime_lifecycle_control": True,
        "uses_existing_safety_runtime_session": True,
        "processes_observation": False,
        "calls_safety_api": False,
        "writes_phase2_brain": False,
        "mutates_runtime_export": False,
        "mutates_activation_request": False,
        "incident_bridge_enabled": False,
        "raw_payloads_embedded": False,
        "notes": [
            "Runtime lifecycle controls / runtime 生命週期控制 update local runtime state only.",
            "Pause, resume, end, and abort do not process new observations.",
            "Safety APIs, incident bridge, and Phase 2 writeback remain disabled.",
        ],
    }

    record_path = (
        state_root
        / DEFAULT_RUNTIME_LIFECYCLE_RECORD_DIR
        / "lifecycle.pause.chilai_nanhua_day1.quick_review.v0.json"
    )
    assert load_runtime_lifecycle_control_record(record_path) == paused.lifecycle_record
    serialized = ended.lifecycle_record.to_json()
    assert "<gpx" not in serialized
    assert "/private/" not in serialized


def test_runtime_lifecycle_controls_abort_is_terminal(tmp_path):
    state_root = tmp_path / "runtime_state"
    observing = _started_observing(tmp_path, state_root)

    aborted = apply_runtime_lifecycle_control(
        observing,
        state_root,
        action=RuntimeLifecycleAction.ABORT,
        control_id="lifecycle.abort.chilai_nanhua_day1.quick_review.v0",
        controlled_by="operator:alex",
        controlled_at="2026-05-18T10:02:00+08:00",
        control_reason="Operator aborts the runtime session.",
    )

    assert aborted.status == RuntimeActivationLoaderStatus.ABORTED
    assert aborted.lifecycle_record.terminal_state is True
    assert aborted.lifecycle_record.counts.observations_processed_count == 1

    try:
        apply_runtime_lifecycle_control(
            aborted,
            state_root,
            action=RuntimeLifecycleAction.RESUME,
            control_id="lifecycle.resume_after_abort.chilai_nanhua_day1.quick_review.v0",
            controlled_by="operator:alex",
            controlled_at="2026-05-18T10:03:00+08:00",
            control_reason="Terminal runtime state should not resume.",
        )
    except ValueError as exc:
        assert "terminal runtime lifecycle state cannot transition" in str(exc)
    else:
        raise AssertionError("expected terminal lifecycle transition rejection")


def test_runtime_lifecycle_controls_reject_invalid_transitions(tmp_path):
    state_root = tmp_path / "runtime_state"
    observing = _started_observing(tmp_path, state_root)

    try:
        apply_runtime_lifecycle_control(
            observing,
            state_root,
            action=RuntimeLifecycleAction.RESUME,
            control_id="lifecycle.invalid_resume.chilai_nanhua_day1.quick_review.v0",
            controlled_by="operator:alex",
            controlled_at="2026-05-18T10:02:00+08:00",
            control_reason="Resume should require paused state.",
        )
    except ValueError as exc:
        assert "resume requires paused runtime state" in str(exc)
    else:
        raise AssertionError("expected invalid resume rejection")


def test_runtime_observation_batch_processes_bounded_observations_without_api(tmp_path):
    state_root = tmp_path / "runtime_state"
    observing = _started_observing(tmp_path, state_root)

    batch = process_runtime_observation_batch(
        observing,
        state_root,
        [
            Observation(
                timestamp=60.0,
                source="watch_batch",
                lat=24.000010,
                lon=121.000010,
                elevation_m=1001.0,
                gps_horizontal_accuracy_m=9.0,
                raw={"sensorlog": {"loggingTime": "2026-05-08T00:01:00Z"}},
            ),
            Observation(
                timestamp=120.0,
                source="watch_batch",
                lat=24.000020,
                lon=121.000020,
                elevation_m=1002.0,
                gps_horizontal_accuracy_m=10.0,
                raw={"sensorlog": {"loggingTime": "2026-05-08T00:02:00Z"}},
            ),
        ],
        batch_id="observation_batch.chilai_nanhua_day1.quick_review.v0",
        processed_by="operator:alex",
        processed_at="2026-05-18T10:05:00+08:00",
        process_reason="Operator imports a bounded field observation batch.",
    )

    assert batch.status == RuntimeActivationLoaderStatus.OBSERVING
    assert batch.session is observing.session
    assert batch.session.snapshot().observations_processed == 3

    record = batch.observation_batch_record
    assert record.previous_status == "observing"
    assert record.status == "observing"
    assert record.observation_count == 2
    assert record.first_observation_timestamp == 60.0
    assert record.last_observation_timestamp == 120.0
    assert record.observation_sources == ["watch_batch"]
    assert record.counts.observations_processed_count == 3
    assert record.counts.safety_api_call_count == 0
    assert record.counts.phase2_writeback_count == 0
    assert record.boundary.model_dump(mode="json") == {
        "phase1_runtime_loader": True,
        "uses_existing_safety_runtime_session": True,
        "starts_observation_processing": True,
        "accepts_bounded_observation_batch": True,
        "connects_continuous_sensor_stream": False,
        "calls_safety_api": False,
        "writes_phase2_brain": False,
        "mutates_runtime_export": False,
        "mutates_activation_request": False,
        "incident_bridge_enabled": False,
        "raw_observations_embedded": False,
        "activation_state": "observing",
        "notes": [
            "Runtime observation batch / 現場觀測批次 accepts a bounded list of observations.",
            "This is not a continuous sensor stream or HTTP safety API.",
            "Phase 2 writeback and incident bridge remain disabled.",
        ],
    }

    record_path = (
        state_root
        / DEFAULT_RUNTIME_OBSERVATION_BATCH_RECORD_DIR
        / "observation_batch.chilai_nanhua_day1.quick_review.v0.json"
    )
    assert load_runtime_observation_batch_record(record_path) == record
    serialized = record.to_json()
    assert "<gpx" not in serialized
    assert "loggingTime" not in serialized


def test_runtime_observation_batch_rejects_paused_and_terminal_states(tmp_path):
    state_root = tmp_path / "runtime_state"
    observing = _started_observing(tmp_path, state_root)
    paused = apply_runtime_lifecycle_control(
        observing,
        state_root,
        action=RuntimeLifecycleAction.PAUSE,
        control_id="lifecycle.pause_for_batch.chilai_nanhua_day1.quick_review.v0",
        controlled_by="operator:alex",
        controlled_at="2026-05-18T10:02:00+08:00",
        control_reason="Operator pauses field observation.",
    )

    try:
        process_runtime_observation_batch(
            paused,
            state_root,
            [Observation(timestamp=60.0, source="watch_batch", lat=24.0, lon=121.0)],
            batch_id="observation_batch.paused.chilai_nanhua_day1.quick_review.v0",
            processed_by="operator:alex",
            processed_at="2026-05-18T10:05:00+08:00",
            process_reason="Paused runtime should reject observations.",
        )
    except ValueError as exc:
        assert "requires observing runtime state" in str(exc)
    else:
        raise AssertionError("expected paused observation batch rejection")

    ended = apply_runtime_lifecycle_control(
        paused,
        state_root,
        action=RuntimeLifecycleAction.END,
        control_id="lifecycle.end_for_batch.chilai_nanhua_day1.quick_review.v0",
        controlled_by="operator:alex",
        controlled_at="2026-05-18T10:04:00+08:00",
        control_reason="Operator ends the runtime session.",
    )
    try:
        process_runtime_observation_batch(
            ended,
            state_root,
            [Observation(timestamp=120.0, source="watch_batch", lat=24.0, lon=121.0)],
            batch_id="observation_batch.ended.chilai_nanhua_day1.quick_review.v0",
            processed_by="operator:alex",
            processed_at="2026-05-18T10:06:00+08:00",
            process_reason="Terminal runtime should reject observations.",
        )
    except ValueError as exc:
        assert "requires observing runtime state" in str(exc)
    else:
        raise AssertionError("expected terminal observation batch rejection")


def test_runtime_observation_batch_rejects_empty_and_duplicate_batches(tmp_path):
    state_root = tmp_path / "runtime_state"
    observing = _started_observing(tmp_path, state_root)

    try:
        process_runtime_observation_batch(
            observing,
            state_root,
            [],
            batch_id="observation_batch.empty.chilai_nanhua_day1.quick_review.v0",
            processed_by="operator:alex",
            processed_at="2026-05-18T10:05:00+08:00",
            process_reason="Empty batch should fail.",
        )
    except ValueError as exc:
        assert "requires at least one observation" in str(exc)
    else:
        raise AssertionError("expected empty batch rejection")

    process_runtime_observation_batch(
        observing,
        state_root,
        [Observation(timestamp=60.0, source="watch_batch", lat=24.0, lon=121.0)],
        batch_id="observation_batch.duplicate.chilai_nanhua_day1.quick_review.v0",
        processed_by="operator:alex",
        processed_at="2026-05-18T10:05:00+08:00",
        process_reason="First batch succeeds.",
    )
    try:
        process_runtime_observation_batch(
            observing,
            state_root,
            [Observation(timestamp=120.0, source="watch_batch", lat=24.0, lon=121.0)],
            batch_id="observation_batch.duplicate.chilai_nanhua_day1.quick_review.v0",
            processed_by="operator:alex",
            processed_at="2026-05-18T10:06:00+08:00",
            process_reason="Duplicate batch id should fail.",
        )
    except FileExistsError as exc:
        assert "runtime observation batch record already exists" in str(exc)
    else:
        raise AssertionError("expected duplicate observation batch rejection")


def test_runtime_stream_guard_blocks_continuous_stream_without_api(tmp_path):
    state_root = tmp_path / "runtime_state"
    observing = _started_observing(tmp_path, state_root)

    guard = request_runtime_stream_start(
        observing,
        state_root,
        stream_request_id="stream_guard.watch.chilai_nanhua_day1.quick_review.v0",
        stream_source_kind="watch_sensor_stream",
        requested_by="operator:alex",
        requested_at="2026-05-18T10:06:00+08:00",
        request_reason="Operator tries to start live watch stream.",
    )

    assert guard.status == "stream_blocked"
    assert guard.session is observing.session
    assert guard.session.snapshot().observations_processed == 1
    record = guard.stream_guard_record
    assert record.status == "stream_blocked"
    assert record.requested_from_status == "observing"
    assert record.stream_source_kind == "watch_sensor_stream"
    assert record.counts.observations_processed_count == 1
    assert record.counts.blocker_count == 1
    assert record.counts.safety_api_call_count == 0
    assert record.counts.phase2_writeback_count == 0
    assert record.boundary.model_dump(mode="json") == {
        "continuous_sensor_stream_allowed": False,
        "hardware_stream_control_allowed": False,
        "safety_api_calls_allowed": False,
        "writes_phase2_brain": False,
        "mutates_runtime_export": False,
        "mutates_activation_request": False,
        "incident_bridge_enabled": False,
        "raw_stream_payloads_embedded": False,
        "requires_future_stream_protocol": True,
        "notes": [
            "Runtime stream guard / 連續串流守門 blocks continuous stream start in this slice.",
            "Bounded observation batches are allowed, but live device or HTTP streams require a future protocol.",
            "Safety APIs, incident bridge, and Phase 2 writeback remain disabled.",
        ],
    }
    assert [finding.finding_id for finding in record.findings] == [
        "runtime_stream_protocol_not_defined"
    ]

    record_path = (
        state_root
        / DEFAULT_RUNTIME_STREAM_GUARD_RECORD_DIR
        / "stream_guard.watch.chilai_nanhua_day1.quick_review.v0.json"
    )
    assert load_runtime_stream_guard_record(record_path) == record
    serialized = record.to_json()
    assert "loggingTime" not in serialized
    assert "<gpx" not in serialized


def test_runtime_stream_guard_records_paused_and_terminal_requests(tmp_path):
    state_root = tmp_path / "runtime_state"
    observing = _started_observing(tmp_path, state_root)
    paused = apply_runtime_lifecycle_control(
        observing,
        state_root,
        action=RuntimeLifecycleAction.PAUSE,
        control_id="lifecycle.pause_for_stream.chilai_nanhua_day1.quick_review.v0",
        controlled_by="operator:alex",
        controlled_at="2026-05-18T10:02:00+08:00",
        control_reason="Operator pauses field observation.",
    )
    paused_guard = request_runtime_stream_start(
        paused,
        state_root,
        stream_request_id="stream_guard.paused.chilai_nanhua_day1.quick_review.v0",
        stream_source_kind="phone_sensor_stream",
        requested_by="operator:alex",
        requested_at="2026-05-18T10:06:00+08:00",
        request_reason="Paused runtime stream request should be recorded as blocked.",
    )
    ended = apply_runtime_lifecycle_control(
        paused,
        state_root,
        action=RuntimeLifecycleAction.END,
        control_id="lifecycle.end_for_stream.chilai_nanhua_day1.quick_review.v0",
        controlled_by="operator:alex",
        controlled_at="2026-05-18T10:04:00+08:00",
        control_reason="Operator ends the runtime session.",
    )
    ended_guard = request_runtime_stream_start(
        ended,
        state_root,
        stream_request_id="stream_guard.ended.chilai_nanhua_day1.quick_review.v0",
        stream_source_kind="phone_sensor_stream",
        requested_by="operator:alex",
        requested_at="2026-05-18T10:07:00+08:00",
        request_reason="Terminal runtime stream request should be recorded as blocked.",
    )

    assert paused_guard.stream_guard_record.requested_from_status == "paused"
    assert ended_guard.stream_guard_record.requested_from_status == "ended"
    assert paused_guard.stream_guard_record.counts.observations_processed_count == 1
    assert ended_guard.stream_guard_record.counts.observations_processed_count == 1


def test_runtime_stream_guard_rejects_duplicate_request_id(tmp_path):
    state_root = tmp_path / "runtime_state"
    observing = _started_observing(tmp_path, state_root)

    request_runtime_stream_start(
        observing,
        state_root,
        stream_request_id="stream_guard.duplicate.chilai_nanhua_day1.quick_review.v0",
        stream_source_kind="watch_sensor_stream",
        requested_by="operator:alex",
        requested_at="2026-05-18T10:06:00+08:00",
        request_reason="First stream guard record succeeds.",
    )
    try:
        request_runtime_stream_start(
            observing,
            state_root,
            stream_request_id="stream_guard.duplicate.chilai_nanhua_day1.quick_review.v0",
            stream_source_kind="watch_sensor_stream",
            requested_by="operator:alex",
            requested_at="2026-05-18T10:07:00+08:00",
            request_reason="Duplicate stream guard id should fail.",
        )
    except FileExistsError as exc:
        assert "runtime stream guard record already exists" in str(exc)
    else:
        raise AssertionError("expected duplicate runtime stream guard rejection")


def test_runtime_activation_loader_blocks_failed_dry_run_without_session(tmp_path):
    _, export_root = _runtime_export_with_activation_request(tmp_path)
    state_root = tmp_path / "runtime_state"
    (export_root / "route_artifacts" / "chilai_nanhua_day1.gpx").unlink()

    result = activate_runtime_export(
        export_root,
        state_root,
        activation_id="activation.chilai_nanhua_day1.quick_review.v0",
        activated_by="operator:alex",
        activated_at="2026-05-18T10:00:00+08:00",
        activation_reason="Route artifact regression should block activation.",
    )

    assert result.status == RuntimeActivationLoaderStatus.ACTIVATION_BLOCKED
    assert result.session is None
    assert result.activation_record is None
    assert result.blocked_report is not None
    assert result.blocked_report.counts.safety_runtime_session_count == 0
    assert result.blocked_report.counts.runtime_activation_record_count == 0
    finding_ids = {finding.finding_id for finding in result.blocked_report.findings}
    assert "activation_preflight_not_ready" in finding_ids
    assert "route_artifact_missing" in finding_ids
    assert not (
        state_root
        / DEFAULT_RUNTIME_ACTIVATION_RECORD_DIR
        / "activation.chilai_nanhua_day1.quick_review.v0.json"
    ).exists()

    blocked_path = state_root / DEFAULT_RUNTIME_ACTIVATION_BLOCKED_REPORT_NAME
    assert load_runtime_activation_blocked_report(blocked_path) == result.blocked_report


def test_runtime_activation_loader_rejects_repo_fixture_state_root(tmp_path):
    _, export_root = _runtime_export_with_activation_request(tmp_path)
    fixture_state_root = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "pretrip"
        / "runtime_state"
    )

    try:
        activate_runtime_export(
            export_root,
            fixture_state_root,
            activation_id="activation.chilai_nanhua_day1.quick_review.v0",
            activated_by="operator:alex",
            activated_at="2026-05-18T10:00:00+08:00",
            activation_reason="Repo fixture state root should be rejected.",
        )
    except ValueError as exc:
        assert "must not be written to repo fixtures" in str(exc)
    else:
        raise AssertionError("expected repo fixture state root rejection")


def test_runtime_activation_loader_source_does_not_observe_or_call_safety_api():
    import runtime_activation_loader

    source = inspect.getsource(runtime_activation_loader)

    assert "SafetyRuntimeSession(" in source
    assert ".observe(" in source
    assert "requests." not in source
    assert "httpx." not in source
    assert "from phase1_incident_bridge" not in source
    assert "Phase1IncidentBridge(" not in source
    assert "/safety/" not in source


def _started_observing(tmp_path: Path, state_root: Path):
    _, export_root = _runtime_export_with_activation_request(tmp_path)
    activation = activate_runtime_export(
        export_root,
        state_root,
        activation_id="activation.chilai_nanhua_day1.quick_review.v0",
        activated_by="operator:alex",
        activated_at="2026-05-18T10:00:00+08:00",
        activation_reason="Operator starts Phase 1 runtime session from reviewed export.",
    )
    return start_runtime_observing(
        activation,
        state_root,
        Observation(
            timestamp=0.0,
            source="operator_initial_fix",
            lat=24.000000,
            lon=121.000000,
            elevation_m=1000.0,
            gps_horizontal_accuracy_m=8.0,
            raw={"sensorlog": {"loggingTime": "2026-05-08T00:00:00Z"}},
        ),
        observing_id="observing.chilai_nanhua_day1.quick_review.v0",
        started_by="operator:alex",
        started_at="2026-05-18T10:01:00+08:00",
        start_reason="Operator confirms first field observation.",
    )
