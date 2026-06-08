import json
import tempfile
from pathlib import Path

from runtime_remote_provider_demo_bundle import build_external_webhook_demo_bundle


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_external_webhook_demo_bundle_blocks_until_operator_secret_refs_are_available():
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = build_external_webhook_demo_bundle(tmpdir)

        assert summary.status == "blocked_missing_secret_refs"
        assert summary.localhost_only is False
        assert summary.external_network_allowed is True
        assert summary.secret_values_embedded is False
        assert summary.raw_payloads_embedded is False
        assert summary.remote_notification_send_count == 0
        assert summary.incident_bridge_enable_count == 0
        assert summary.phase2_writeback_count == 0
        assert summary.missing_secret_refs == summary.required_secret_refs

        config = _load(summary.provider_config_path)
        send_intent = _load(summary.send_intent_path)
        secret_refs = _load(summary.secret_refs_path)
        command = Path(summary.operator_command_path).read_text(encoding="utf-8")
        combined = "\n".join(
            Path(path).read_text(encoding="utf-8")
            for path in (
                summary.provider_config_path,
                summary.send_intent_path,
                summary.payload_preview_path,
                summary.operator_command_path,
                summary.secret_refs_path,
            )
        )

        assert config["endpoint"]["raw_url_embedded"] is False
        assert config["auth"]["token_value_embedded"] is False
        assert send_intent["status"] == "send_intent_blocked"
        assert secret_refs["raw_endpoint_url_embedded"] is False
        assert secret_refs["secret_values_embedded"] is False
        assert "export SCOUT_REMOTE_WEBHOOK_URL=<operator-provided-secret>" in command
        assert "https://example.invalid" not in combined
        assert "operator-secret-not-exported" not in combined
        assert "Phase1IncidentBridge" not in combined
        assert "Phase2Brain" not in combined


def test_external_webhook_demo_bundle_can_be_marked_ready_without_embedding_values():
    with tempfile.TemporaryDirectory() as tmpdir:
        required_refs = {
            "env:SCOUT_REMOTE_WEBHOOK_URL",
            "env:SCOUT_REMOTE_WEBHOOK_TOKEN",
            "env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET",
            "env:SCOUT_REMOTE_PRIMARY_TARGET_REF",
            "env:SCOUT_REMOTE_BACKUP_TARGET_REF",
        }
        summary = build_external_webhook_demo_bundle(
            tmpdir,
            available_secret_refs=required_refs,
        )

        assert summary.status == "ready_requires_manual_send"
        assert summary.provider_config_status == "provider_config_ready"
        assert summary.payload_preview_status == "payload_ready_not_sent"
        assert summary.send_intent_status == "queued_not_sent"
        assert summary.missing_secret_refs == []
        assert set(summary.required_secret_refs) == required_refs
        assert summary.secret_values_embedded is False

        send_intent = _load(summary.send_intent_path)
        payload_preview = _load(summary.payload_preview_path)
        secret_refs = _load(summary.secret_refs_path)

        assert send_intent["send_intent_queued"] is True
        assert send_intent["sends_network_request"] is False
        assert payload_preview["send_performed"] is False
        assert secret_refs["external_network_allowed_after_manual_authorization"] is True
