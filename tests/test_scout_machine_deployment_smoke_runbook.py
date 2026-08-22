from __future__ import annotations

import re
from pathlib import Path


RUNBOOK_PATH = Path("docs/admin/scout-machine-deployment-smoke.md")


def read_runbook() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def test_scout_machine_deployment_smoke_runbook_is_chinese_first() -> None:
    source = read_runbook()
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", source)
    latin_words = re.findall(r"[A-Za-z]{2,}", source)

    assert len(cjk_chars) > 450
    assert len(cjk_chars) > len(latin_words)
    assert "這份 runbook 是 hardware prototype prep 的人工 smoke 測試指南" in source


def test_runbook_keeps_prototype_prep_offline_until_operator_runs_manual_steps() -> None:
    source = read_runbook()

    for token in (
        "offline preflight",
        "不連 Pi",
        "不啟動 Docker",
        "不啟動 Ollama",
        "不啟動本地模型",
        "不呼叫 live `/safety/*` mutation",
        "不送 outbound",
        "不控制 hardware provider",
        "manual-only",
    ):
        assert token in source


def test_runbook_documents_step1_environment_and_manual_smoke_ladder() -> None:
    source = read_runbook()

    for token in (
        "SCOUT_DATA_ROOT=/data/scout",
        "SCOUT_RUNTIME_PROFILE=pi-field",
        "SCOUT_ENABLE_LIVE_HARDWARE=0",
        "SCOUT_ENABLE_AI_INFERENCE=0",
        "SCOUT_EVENT_BUS=none",
        "curl --max-time 5 http://scout.local:9099/health",
        "curl --max-time 5 http://scout.local:9099/runtime/status",
        "curl --max-time 5 http://scout.local:9099/providers/status",
        "http://scout.local:9099/safety/observations",
    ):
        assert token in source


def test_runbook_documents_host_side_radio_scan_boundary() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_radio_scan_smoke.py",
        "radio_environment_scan",
        "/data/scout/providers/radio_scan/manual-smoke.jsonl",
        "fixed read-only `boundary` block",
        "驗證 `radio_counts`",
        "不呼叫 `/safety/observations`",
        "不寫 IncidentStore",
        "不寫 ObservedFact",
        "不寫 Phase 2 Brain",
        "不送 outbound",
        "不控制 hardware provider",
        "不控制 Phase 1 safety decision",
    ):
        assert token in source


def test_runbook_documents_host_side_ins_dr_validation() -> None:
    source = read_runbook()

    for token in (
        "Host-side INS/DR local validation",
        "tests/test_ins_dr_input_adapter.py",
        "tests/test_ins_dr_navigation.py",
        "tests/test_ins_dr_navigation_smoke.py",
        "tests/test_ins_dr_field_evidence_check.py",
        "tests/test_ins_dr_field_proof_pipeline.py",
        "tests/test_ins_dr_field_completion_gate.py",
        "tests/test_ins_dr_diagnostic_route_scaffold.py",
        "tests/test_ins_dr_field_readiness_check.py",
        "tests/test_ins_dr_gnss_fix_watch.py",
        "tests/test_ins_dr_field_session.py",
        "tests/test_ins_dr_field_movement_drill.py",
        "tests/test_ins_dr_manual_field_run.py",
        "tests/test_ins_dr_live_field_proof.py",
        "tests/test_ins_dr_proof_manifest_check.py",
        "tests/test_ins_dr_runtime_smoke.py",
        "tests/test_pi_dr_delta_smoke.py",
        "tests/test_pi_wheel_odometry_delta_smoke.py",
        "tests/test_pi_wheel_encoder_gpio_smoke.py",
        "ins_dr_navigation.py",
        "tools/ins_dr_navigation_smoke.py",
        "tools/ins_dr_runtime_smoke.py",
        "tools/ins_dr_field_evidence_check.py",
        "tools/ins_dr_field_proof_pipeline.py",
        "tools/ins_dr_proof_manifest_check.py",
        "tools/ins_dr_field_completion_gate.py",
        "tools/ins_dr_diagnostic_route_scaffold.py",
        "tools/ins_dr_field_readiness_check.py",
        "tools/ins_dr_gnss_fix_watch.py",
        "tools/pi_gnss_physical_checklist.py",
        "tools/ins_dr_field_session.py",
        "tools/ins_dr_field_movement_drill.py",
        "tools/ins_dr_manual_field_run.py",
        "tools/ins_dr_live_field_proof.py",
        "tools/pi_dr_delta_smoke.py",
        "tools/pi_wheel_odometry_delta_smoke.py",
        "tools/pi_wheel_encoder_gpio_smoke.py",
        "DeadReckoningDelta",
        "vendor_fusion_disagreement",
        "不可覆蓋 raw GNSS + DR estimate",
        "diagnostic navigation estimate",
        "diagnostic_runtime_ingest_replay_only",
        "diagnostic_field_evidence_review_only",
        "diagnostic_field_proof_pipeline_only",
        "proof-manifest.json",
        "diagnostic_field_proof_manifest_only",
        "diagnostic_field_proof_manifest_verification_only",
        "diagnostic_field_completion_gate_only",
        "diagnostic_route_scaffold_only",
        "diagnostic_field_readiness_check_only",
        "diagnostic_gnss_fix_watch_only",
        "diagnostic_field_movement_drill_only",
        "field-movement-drill-report.json",
        "drill_profile=gnss_anchor_then_live_gpio_wheel_then_reanchor",
        "--dry-run-plan",
        "window_stability",
        "valid_fix_window_count",
        "gps_cno_window_count",
        "any_cno_window_count",
        "no_rf_window_count",
        "intermittent_rf_observed",
        "talker_signal_summary",
        "talkers=GP",
        "diagnostic_field_session_orchestration_only",
        "operator_entered_measurement_interpretation_only",
        "diagnostic_manual_field_run_only",
        "diagnostic_live_field_proof_only",
        "gnss_field_capture_not_replayed_fixture",
        "raw_gnss_checksum_valid_for_navigation",
        "capture_mode=serial_device",
        "raw_nmea_argument",
        "invalid_gnss_checksum_diagnostic_only",
        "primary_truth_scope=diagnostic_replayed_nmea_only",
        "field_proof_status=passed",
        "route_corridor_inside_for_navigation",
        "dr_distance_source_allowed_for_navigation",
        "dr_distance_source_summary",
        "dr_distance_source_failure_count",
        "observation_dr_source_kind",
        "observation_dr_navigation_allowed",
        "observation_provider_hardware_control_scope",
        "observation_odometry_delta_method",
        "observation_previous_raw_evidence_ref",
        "observation_current_raw_evidence_ref",
        "missing_wheel_encoder_provider_provenance",
        "dr_heading_available_for_navigation",
        "observation_dr_heading_deg",
        "heading_unavailable",
        "dead_reckoning_input.heading_deg",
        "dr_heading_summary",
        "manual_operator_distance_delta",
        "field_rehearsal_only",
        "proof_manifest_status=passed",
        "scout_ins_dr_navigation_status=field_ready",
        "completion_ready=true",
        "field_run_readiness_status=ready",
        "gnss_serial_port_exists",
        "--gnss-port auto",
        "--gnss-evidence-jsonl",
        "--auto-select-gnss-by-fix-duration-seconds",
        "--auto-select-gnss-evidence-dir",
        "gnss_auto_selection_summary.selection_status=selected_valid_fix_candidate",
        "gnss_auto_selection_has_valid_fix_candidate",
        "pi_gnss_ab_compare.py",
        "--auto-capture",
        "--auto-baud",
        "--include-uart",
        "--placement",
        "--placement-port",
        "--placement-settle-seconds",
        "gnss-placement-sweep.json",
        "placement_sweep.best_placement_label",
        "placements_with_gps_rf_signal",
        "placements_with_any_rf_signal",
        "pi_gnss_signal_monitor.py",
        "gnss-signal-monitor-windows.jsonl",
        "gnss-signal-monitor-report.json",
        "talker_signal_summary",
        "talkers=GP",
        "valid_fix_observed_hold_position_and_run_movement_drill",
        "rf_is_intermittent_adjust_mounting_and_reduce_shielding",
        "auto_serial_candidates",
        "labels_with_gps_rf_signal",
        "pi_gnss_hardware_snapshot.py",
        "--auto-targets",
        "auto_serial_candidate_count",
        "field-session-report.json",
        "field-session-next-action.json",
        "field-session-next-action.md",
        "next_action_status=collect_physical_measurements",
        "repair_physical_fault",
        "fix_gnss_rf_or_antenna",
        "wait_for_valid_fix",
        "run_live_proof_next",
        "--gnss-watch-before-readiness",
        "--gnss-watch-window-seconds",
        "--gnss-watch-max-wait-seconds",
        "gnss_watch_status=valid_fix_observed",
        "gnss_watch_status=timed_out_no_rf_signal",
        "field_session_status=gnss_watch_not_ready",
        "gnss-fix-watch-events.jsonl",
        "gnss-fix-watch-payloads.jsonl",
        "gnss-fix-watch-report.json",
        "--stop-on valid_fix",
        "--stop-on gps_cno",
        "--stop-on any_cno",
        "watch_status=valid_fix_observed",
        "watch_status=gps_cno_observed_without_fix",
        "watch_status=timed_out_no_rf_signal",
        "--write-template",
        "--measurements-json",
        "--gnss-physical-measurements-json",
        "gnss-physical-checklist-report.json",
        "physical_fault_indicated",
        "VCC under-load",
        "RF_IN 對地短路",
        "active antenna bias",
        "known-good GPS L1 antenna",
        "gnss-hardware-snapshot.json",
        "gnss-diagnosis-report.json",
        "field-readiness-report.json",
        "--run-live-proof",
        "readiness_not_ready",
        "ready_for_live_proof",
        "live_proof_completed",
        "--gnss-hardware-snapshot-json",
        "gnss_hardware_snapshot_loaded",
        "gnss_hardware_snapshot_summary.verdict.next_required_evidence",
        "gps_rf_fault_strongly_supported_labels",
        "--capture-gnss-duration-seconds",
        "--capture-gnss-evidence-jsonl",
        "gnss_live_evidence_capture_completed",
        "gnss_live_capture_summary.fix.valid_fix_count",
        "gnss-readiness-capture.jsonl",
        "--require-valid-gnss-fix",
        "gnss_evidence_has_rf_signal_or_fix",
        "gnss_evidence_has_valid_fix",
        "gnss_fix_summary.valid_fix_count",
        "gnss_fix_summary.latest_valid_fix.position",
        "gnss_evidence_summary.signal.max_cno_dbhz",
        "gnss_readiness_diagnosis.state",
        "gnss_watch_talker_signal_summary",
        "readiness_gnss_talker_signal_summary",
        "readiness_gnss_best_talker=GL",
        "valid_fix_ready",
        "rf_signal_without_valid_fix",
        "non_gps_rf_signal_without_valid_fix",
        "gps_max_cno_dbhz=null",
        "no_nmea_payloads",
        "nmea_without_gsv_or_fix",
        "next_operator_action",
        "selected_gnss_port",
        "--readiness-report-json",
        "selected_from_readiness_report",
        "ready_for_live_field_proof=true",
        "ambiguous_serial_candidates",
        "/dev/serial/by-id/",
        "live-field-proof-report.json",
        "operator-events.jsonl",
        "diagnostic_live_field_proof_operator_guidance_only",
        "raw_nmea_rehearsal_no_serial_required",
        "--anchor-wait-timeout-seconds",
        "--anchor-retry-interval-seconds",
        "anchor_capture_attempt",
        "anchor_capture_summary",
        "--reanchor-wait-timeout-seconds",
        "--reanchor-retry-interval-seconds",
        "reanchor_capture_attempt",
        "reanchor_capture_summary",
        "--wheel-odometry-jsonl",
        "dr_evidence_mode=wheel_odometry_jsonl",
        "wheel_odometry_record_count",
        "--heading-evidence-jsonl",
        "heading_evidence_payload_count",
        "heading_evidence_jsonl_paths",
        "raw IMU heading JSONL",
        "--movement-window-seconds",
        "movement_window_seconds",
        "failure_stage=anchor_capture",
        "anchor_gnss_signal_summary",
        "anchor_failure_diagnosis.state",
        "no_rf_signal_observed",
        "rf_signal_without_valid_fix",
        "proof_manifest_status=not_created",
        "--allow-overwrite",
        "process exit code 為 0",
        "都有 `sha256`",
        "--require-reanchor",
        "gnss_reanchor",
        "latest_route_progress_sample.estimate_source=dead_reckoning",
        "observation_lat=null",
        "diagnostic_odometry_delta_only",
        "diagnostic_wheel_odometry_delta_only",
        "diagnostic_gpio_wheel_encoder_capture_only",
        "wheel-dr-delta.jsonl",
        "wheel-raw.jsonl",
        "wheel-encoder-gpio-capture.jsonl",
        "--require-live-positive-movement",
        "live_positive_wheel_movement_ready",
        "left_tick_delta",
        "right_tick_delta",
        "line_activity_observed",
        "left_level_change_delta",
        "right_level_change_delta",
        "missing_reason",
        "--live-wheel-encoder-gpio-capture",
        "--wheel-encoder-gpio-capture",
        "wheel_encoder_gpio_capture_start",
        "wheel_encoder_gpio_capture_complete",
        "movement_window_consumed_by_wheel_encoder_capture",
        "GNSS anchor -> live wheel encoder capture -> DR delta -> GNSS re-anchor",
        "cumulative_distance_m",
        "left_ticks",
        "right_ticks",
        "meters-per-tick",
        "previous_raw_evidence_ref",
        "current_raw_evidence_ref",
        "odometry_delta_method",
        "raw.odometry.distance_delta_m",
        "raw.dr.distance_delta_m",
        "distance_delta_m",
        "--wheel-encoder-gpio-capture",
        "--wheel-meters-per-tick",
        "Live no-fix DR-only path",
        "`/safety/observations` direct ingest",
        "latest_position_estimate",
        "operator 明確開始 prototype",
        "source=dead_reckoning",
        "raw_gnss+dead_reckoning",
    ):
        assert token in source


def test_runbook_documents_field_wifi_oled_status_diagnostic() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_wifi_oled_status.py",
        "Field Wi-Fi OLED status diagnostic",
        "--interface wlan0",
        "--source nmcli",
        "/data/scout/providers/wifi_oled/boot-status.jsonl",
        "`SCOUT WIFI`",
        "`IP ...`",
        "`ON ...`",
        "`AP N`",
        "`SCAN ERR`",
        "one-shot systemd service",
        "After=NetworkManager.service",
        "不呼叫 live `/safety/*` mutation",
        "不送 outbound",
        "不改 Phase 1 safety",
        "不會替 Pi 新增、修改或切換 Wi-Fi 連線",
        "Scout field AP fallback",
    ):
        assert token in source


def test_runbook_links_focused_local_validation_command() -> None:
    source = read_runbook()

    assert (
        "/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest "
        "tests/test_scout_hardware_prototype_prep.py "
        "tests/test_scout_machine_deployment_smoke_runbook.py"
    ) in source


def test_runbook_documents_local_admin_assistant_prototype_gate() -> None:
    source = read_runbook()

    for token in (
        "Local Admin / Assistant Prototype Gate",
        "admin_hardware_prototype_smoke_check.py",
        "SCOUT_BROWSER_NODE",
        "SCOUT_BROWSER_NODE_PATH",
        "--browser-mode required",
        "GET /assistant/status",
        "provider 是 `mock`",
        "assistant_ui_smoke_check.py --pretty",
        "assistant_readiness_check.py --pretty",
        "assistant_browser_smoke_check.py --base-url http://127.0.0.1:9111 --pretty",
        "不連 `scout.local`",
        "不啟動 Ollama",
        "不呼叫 `/safety/*` mutation",
        "不控制硬體 provider",
    ):
        assert token in source


def test_runbook_documents_pi_smoke_visual_feedback_wrapper() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_smoke_visual_feedback.py",
        "diagnostic visual feedback",
        "OLED 會顯示 `RUN`",
        "LED Bar 亮前半段",
        "--run-hold-seconds",
        "可讓 RUN 狀態先停留",
        "OLED 顯示 `OK`",
        "LED Bar 全亮",
        "OLED 顯示 `FAIL`",
        "LED Bar 顯示交錯燈號",
        "--require-visual",
        "--visual-dry-run",
        "不呼叫 live `/safety/*` mutation",
        "不送 outbound",
        "不改 Phase 1 safety decision",
    ):
        assert token in source


def test_runbook_documents_gnss_oled_status_summary() -> None:
    source = read_runbook()

    for token in (
        "GNSS NMEA smoke with OLED status",
        "GNSS NMEA smoke with OLED + LED Bar status",
        "--oled-status",
        "--oled-update-seconds 2",
        "--led-status",
        "--led-nofix-bit 1",
        "--led-fix-bit 10",
        "--led-update-seconds 2",
        "--led-blink-count 2",
        "OLED 會顯示 `SCOUT GPS`",
        "`FIX OK` 或 `NO FIX`",
        "Grove LED Bar v2.0 不是 RGB LED",
        "預設 `NO FIX` 閃 LED1",
        "`FIX OK` 閃 LED10",
        "--led-nofix-bit 10 --led-fix-bit 1",
        "diagnostic indicator",
        "NMEA sentence",
        "satellite/fix quality",
        "NMEA signal summary",
        "satellite_signal",
        "gnss_signal_summary",
        "max_cno_dbhz",
        "gps_max_cno_dbhz",
        "nonzero_cno_count",
        "GSV reported_visible_satellites=0",
        "不呼叫 live `/safety/*` mutation",
        "不送 outbound",
        "不改 Phase 1 safety decision",
    ):
        assert token in source


def test_runbook_documents_keypad_4x4_diagnostic_smoke() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_keypad_4x4_smoke.py",
        "4x4 matrix keypad",
        "--grove-ports D16,D18,D24,D26",
        "--active-high",
        "rows `16,17,18,19`",
        "cols `24,25,26,27`",
        "active-high",
        "--simulate-keys S1,S4,S15",
        "不接 VCC、不接 GND",
        "`R1 R2 R3 R4 C1 C2 C3 C4` 八條線接到 GPIO",
        "避開 I2C、UART、LED Bar D5",
        "Physical label",
        "`S4`",
        "`S15`",
        "physical_label",
        "scout_dev_keypad_v1",
        "development control surface",
        "16 個輸入自由度",
        "Grove Button",
        "dedicated safety input",
        "prototype control candidates",
        "final product HMI",
        "不可直接改 L0-L4",
        "`sos_arm_candidate`",
        "不可直接當成 SOS",
        "不可接 live `/safety/*`",
    ):
        assert token in source


def test_runbook_documents_pir_motion_diagnostic_smoke() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_grove_pir_motion_smoke.py",
        "Grove mini PIR motion sensor diagnostic smoke",
        "--port D22",
        "--signal-index 0",
        "--active-high",
        "--simulate-levels 0,1,1,0",
        "`GPIO22`",
        "nearby_motion_candidate",
        "`motion_start`",
        "`motion_end`",
        "OLED 顯示 `SCOUT PIR / MOTION`",
        "LED Bar 預設閃 LED2",
        "不可直接當成 safety decision",
        "不可接 live",
    ):
        assert token in source


def test_runbook_documents_wio_e5_lorawan_at_diagnostic_smoke() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_wio_e5_lorawan_at_smoke.py",
        "Wio-E5 / LoRa-E5 USB serial AT diagnostic smoke",
        "--commands AT,AT+VER,AT+ID",
        "/data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl",
        "/dev/serial/by-id/",
        "Silicon Labs CP210x UART Bridge",
        "`SCOUT LORA`",
        "`AT OK`",
        "`AT FAIL`",
        "`NO RF TX`",
        "LED7",
        "LED10",
        "local USB serial AT diagnostic",
        "不做 LoRaWAN join",
        "不送 uplink",
        "不做 RF test TX",
        "`AT+JOIN`",
        "`AT+MSG`",
        "`AT+CMSG`",
        "`AT+PMSG`",
        "`AT+DTRX`",
        "`AT+SEND`",
        "`AT+TEST`",
        "帶 `=` 的設定/發送型 AT command",
        "不是 Scout safety runtime 的通訊 provider",
        "不可接 live `/safety/*` mutation",
    ):
        assert token in source


def test_runbook_documents_wio_e5_lorawan_uplink_trial_plan() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_wio_e5_lorawan_uplink_trial_plan.py",
        "Wio-E5 / LoRa-E5 client uplink trial plan",
        "--wio-at-jsonl /data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl",
        "--gateway-rx-jsonl /data/scout/providers/lora/sx1303-gateway-rx-readiness.jsonl",
        "--uplink-jsonl /data/scout/providers/lora/sx1303-gateway-uplink.jsonl",
        "--frequency-hz 923200000",
        "--region-profile AS923_2",
        "/data/scout/providers/lora/wio-e5-uplink-trial-plan.jsonl",
        "waiting_for_operator_approval",
        "I_ACCEPT_RF_TX_AS923_2_TW_920_925",
        "ready_for_manual_uplink_trial",
        "`PLAN BLOCKED`",
        "`WAIT APPROVAL`",
        "`NO RF TX`",
        "LED2",
        "LED1",
        "不開 serial",
        "不送 `AT+JOIN`",
        "不送 `AT+MSG`",
        "不送 `AT+TEST`",
        "不使用\n`mosquitto_pub`",
        "不發射 RF",
        "`920000000-925000000 Hz`",
        "`operator_approval_token_stored=false`",
        "`rf_tx_allowed=false`",
        "`lorawan_uplink_allowed=false`",
        "`rf_tx_executed=false`",
        "`lorawan_uplink_executed=false`",
        "真正的 client uplink 需要另一個明確",
    ):
        assert token in source


def test_runbook_documents_wio_e5_operator_approved_rf_trial() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_wio_e5_lorawan_rf_trial.py",
        "Wio-E5 / LoRa-E5 operator-approved RF uplink trial",
        "--plan-jsonl /data/scout/providers/lora/wio-e5-uplink-trial-plan.jsonl",
        "--payload-text SCOUT",
        "--execute-rf-tx",
        "/data/scout/providers/lora/wio-e5-rf-trial.jsonl",
        "--join-only",
        "`rf_trial_join_confirmed_no_uplink`",
        "`ready_for_manual_uplink_trial`",
        "pi_sx1303_gateway_uplink_mqtt_tail.py",
        "`AT+JOIN` / `AT+MSG=\"SCOUT\"`",
        "`I_ACCEPT_RF_TX_AS923_2_TW_920_925`",
        "`--dry-run`",
        "不設定 AppKey / DevEUI / AppEUI / channel mask",
        "不改 ChirpStack",
        "`--continue-after-join-failure`",
        "`--skip-join`",
        "`rf_tx_allowed=true`",
        "`rf_tx_executed=true`",
        "`join_executed=true`",
        "`lorawan_uplink_executed=true`",
        "`phase1_safety_decision_change_allowed=false`",
        "`phase1_l0_l4_state_mutated=false`",
        "`safety_api_called=false`",
        "`downlink_allowed=false`",
        "`remote_outbound_allowed=false`",
        "`SCOUT LORA TX`",
        "`RF SENT`",
        "`RF FAIL`",
        "`BLOCKED`",
        "`DRY RUN`",
        "LED9",
        "LED10",
    ):
        assert token in source


def test_runbook_documents_wio_e5_chirpstack_join_audit() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_wio_e5_chirpstack_join_audit.py",
        "Wio-E5 / ChirpStack join provisioning audit",
        "--wio-at-jsonl /data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl",
        "--rf-trial-jsonl /data/scout/providers/lora/wio-e5-rf-trial.jsonl",
        "--uplink-jsonl /data/scout/providers/lora/sx1303-gateway-uplink.jsonl",
        "--tail-status-jsonl /data/scout/providers/lora/sx1303-gateway-uplink-tail-status.jsonl",
        "/data/scout/providers/lora/wio-e5-chirpstack-join-audit.jsonl",
        "只讀 Wio-E5 AT",
        "Postgres device table read-only query",
        "不改 ChirpStack",
        "不建立 device",
        "不改 AppKey",
        "不發 MQTT",
        "不送 downlink",
        "不送 RF",
        "DevEUI / AppEUI 只輸出 hash",
        "raw log lines",
        "raw device EUI",
        "client_dev_eui_not_registered_in_chirpstack",
        "client_join_failed_no_gateway_join_hint",
        "client_join_failed_network_server_rejected",
        "`uplink_observed`",
        "`SCOUT LORA AUD`",
        "`DEV MISSING`",
        "`NO JOIN HINT`",
        "`JOIN REJECT`",
        "`UL OK`",
        "LED8",
        "LED9",
        "LED10",
        "不是 Scout safety decision source",
        "tools/pi_wio_e5_chirpstack_join_state_reset.py",
        "Wio-E5 / ChirpStack join-state reset dry-run",
        "I_ACCEPT_CHIRPSTACK_JOIN_STATE_RESET_AS923_2",
        "`dry_run_join_state_reset_planned`",
        "`blocked_join_state_reset`",
        "模組與 server join state 不同步或 DevNonce replay",
        "不改 DevEUI / JoinEUI",
    ):
        assert token in source


def test_runbook_documents_wio_e5_chirpstack_as9232_profile_provisioning() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_wio_e5_chirpstack_as9232_profile_provision.py",
        "Wio-E5 / ChirpStack AS923_2 profile provisioning",
        "--wio-at-jsonl /data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl",
        "--allow-in-place-profile-update",
        "I_ACCEPT_CHIRPSTACK_PROFILE_MUTATION_AS923_2",
        "--execute",
        "/data/scout/providers/lora/wio-e5-chirpstack-profile-provision.jsonl",
        "預設不寫入",
        "不送 RF",
        "不送 downlink",
        "不發 MQTT",
        "不改 AppKey",
        "不改 JoinEUI",
        "不建立新 device",
        "`AS923_2` / `as923_2`",
        "`device_profile_id`",
        "`postgres_write_performed`",
        "`chirpstack_config_changed`",
        "`device_registry_changed`",
        "`profile_mutation_scope`",
        "`rf_tx_allowed=false`",
        "`lorawan_uplink_allowed=false`",
        "`downlink_allowed=false`",
        "`safety_api_called=false`",
        "DevEUI、AppEUI 與 key 原文不可輸出",
        "`SCOUT LORA PROV`",
        "`MUTATED`",
        "LED8",
        "LED9",
        "LED10",
    ):
        assert token in source


def test_runbook_documents_wio_e5_chirpstack_key_sync() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_wio_e5_chirpstack_key_sync.py",
        "Wio-E5 / ChirpStack OTAA key sync",
        "--wio-at-jsonl /data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl",
        "--use-existing-chirpstack-key",
        "I_ACCEPT_LORAWAN_KEY_SYNC_AS923_2",
        "--execute",
        "/data/scout/providers/lora/wio-e5-chirpstack-key-sync.jsonl",
        "不做 RF trial",
        "dry-run plan",
        "`AT+KEY=APPKEY",
        "`rf_tx_allowed=false`",
        "`join_executed=false`",
        "`lorawan_uplink_allowed=false`",
        "`downlink_allowed=false`",
        "`mqtt_publish_performed=false`",
        "`safety_api_called=false`",
        "`phase1_safety_decision_change_allowed=false`",
        "`serial_write_performed`",
        "`wio_module_state_changed`",
        "`postgres_write_performed`",
        "`device_keys_changed`",
        "`target_key_fingerprint`",
        "`root_key_printed=false`",
        "`raw_key_embedded=false`",
        "`operator_approval_token_stored=false`",
        "`SCOUT LORA KEY`",
        "`KEY SYNCED`",
        "LED8",
        "LED9",
        "LED10",
    ):
        assert token in source


def test_runbook_documents_sx1303_gateway_gps_nmea_smoke() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_sx1303_gateway_smoke.py",
        "SX1303 Gateway HAT SPI / chip-id RF preflight smoke",
        "--spi-device /dev/spidev0.0",
        "--hal-root /home/alexwang0315/Documents/sx1302_hal_rpi5-master",
        "/data/scout/providers/lora/sx1303-gateway-smoke.jsonl",
        "`util_chip_id`",
        "`RF OK`",
        "`NO RF TX`",
        "LED7",
        "packet_forwarder_started=false",
        "diagnostic_gateway_evidence_only",
        "0x0016c001f11f5f46",
        "仍不代表已收到",
    ):
        assert token in source

    for token in (
        "tools/pi_sx1303_gateway_rx_smoke.py",
        "SX1303 Gateway passive RX readiness smoke",
        "--chirpstack-root /data/scout/providers/lora/chirpstack-docker",
        "/data/scout/providers/lora/sx1303-gateway-rx-readiness.jsonl",
        "`SCOUT LORA RX`",
        "`RX READY NO UL`",
        "不保存 raw log lines",
        "不啟動 packet forwarder",
        "不送 RF",
        "不做 LoRaWAN join/uplink",
        "LED8",
        "LED9",
    ):
        assert token in source

    for token in (
        "tools/pi_sx1303_gateway_uplink_mqtt_tail.py",
        "SX1303 Gateway passive MQTT uplink tail",
        "application/+/device/+/event/up",
        "as923_2/gateway/+/event/up",
        "/data/scout/providers/lora/sx1303-gateway-uplink.jsonl",
        "/data/scout/providers/lora/sx1303-gateway-uplink-tail-status.jsonl",
        "不使用",
        "mosquitto_pub",
        "DevEUI",
        "payload data 不寫入 JSONL",
        "`WAIT UPLINK`",
        "`UPLINK OK`",
    ):
        assert token in source

    for token in (
        "tools/pi_sx1303_gateway_gps_nmea_smoke.py",
        "SX1303 Gateway HAT L76K GPS NMEA UART smoke",
        "--ports /dev/serial0,/dev/ttyAMA0,/dev/ttyAMA10,/dev/ttyS0",
        "--baud-rates 9600,38400,57600,115200",
        "/data/scout/providers/lora/sx1303-gateway-gps-nmea-smoke.jsonl",
        "SX1303 本身不是 NMEA 來源",
        "L76K GNSS",
        "`diagnostic_gateway_gnss_uart_only`",
        "`nmea_ok`",
        "`bad_stream`",
        "`missing_device`",
        "`gps_tty_path`",
        "`selected_port`",
        "`SCOUT GW GPS`",
        "LED10",
        "LED1",
        "不是 Scout safety decision source",
        "scout_gnss_hardware_observer.py",
        "--gateway-jsonl /data/scout/providers/lora/sx1303-gateway-gps-nmea-smoke.jsonl",
        "--grove-jsonl /data/scout/providers/gnss/manual-smoke.jsonl",
        "/data/scout/admin/ingress/gnss_hardware/live_navigation_snapshot.json",
        "`snapshot_status=no_valid_fix`",
        "`live_hardware_read_performed=false`",
        "`lorawan_uplink_allowed=false`",
    ):
        assert token in source
