from phase4_live_demo_loader import (
    build_phase4_live_demo_env,
    build_phase4_live_demo_server_command,
    prepare_phase4_live_demo,
)


def test_phase4_live_demo_plan_names_urls_and_safe_boundaries():
    plan = prepare_phase4_live_demo(host="127.0.0.1", port=9099)

    assert plan["artifact_kind"] == "phase4_live_demo_plan"
    assert plan["status"] == "ready_to_start"
    assert plan["urls"]["pretrip_admin"] == "http://127.0.0.1:9099/admin/pretrip"
    assert plan["urls"]["pretrip_admin_local_tiles"].endswith(
        "/admin/pretrip?tileSource=local"
    )
    assert plan["urls"]["assistant_status"].endswith("/assistant/status")
    assert plan["urls"]["weather_overlay"].endswith(
        "/admin/pretrip/projects/chilai_nanhua_day1/weather-overlay"
    )
    assert plan["network_expectations"]["public_osm_loaded_by_browser"] is True
    assert plan["network_expectations"]["open_meteo_live_weather_enabled"] is True
    assert plan["network_expectations"]["local_osm_proxy_external_fetch_allowed"] is False
    assert plan["network_expectations"]["external_webhook_send_enabled"] is False
    assert plan["boundaries"]["phase1_runtime_mutation_allowed"] is False
    assert plan["boundaries"]["phase2_writeback_allowed"] is False
    assert plan["boundaries"]["assistant_read_only"] is True
    assert plan["boundaries"]["repo_fixture_write_allowed"] is False


def test_phase4_live_demo_server_command_enables_mock_assistant_and_open_meteo():
    command = build_phase4_live_demo_server_command(host="127.0.0.1", port=9099)

    assert "SCOUT_AI_ASSISTANT_ENABLED=1" in command
    assert "SCOUT_AI_ASSISTANT_PROVIDER=mock" in command
    assert "SCOUT_WEATHER_API_ENABLED=true" in command
    assert "SCOUT_WEATHER_API_PROVIDER=open_meteo" in command
    assert "SCOUT_SAFETY_ENABLED=false" in command
    assert "-m uvicorn server:app" in command
    assert "--host 127.0.0.1 --port 9099" in command
    assert "SCOUT_WEATHER_API_KEY" not in command


def test_phase4_live_demo_env_can_disable_live_network_adjacent_features():
    env = build_phase4_live_demo_env(
        enable_live_weather=False,
        enable_assistant=False,
    )

    assert env == {"SCOUT_SAFETY_ENABLED": "false"}
