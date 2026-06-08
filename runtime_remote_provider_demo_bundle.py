from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from runtime_remote_provider_config_preflight import (
    RuntimeRemoteProviderAuthConfig,
    build_webhook_remote_provider_config_template,
    run_runtime_remote_provider_config_preflight,
    RuntimeRemoteProviderEndpointConfig,
    RuntimeRemoteRecipientBinding,
)
from runtime_remote_provider_payload_composer import (
    RuntimeRemoteProviderPayloadRequest,
    compose_runtime_remote_provider_payload,
)
from runtime_remote_provider_policy import (
    RuntimeRemoteMessageClass,
    build_webhook_remote_provider_policy_contract,
)
from runtime_remote_provider_send_queue import queue_runtime_remote_provider_send_intent


DEMO_WEBHOOK_URL_ENV = "SCOUT_REMOTE_WEBHOOK_URL"
DEMO_WEBHOOK_TOKEN_ENV = "SCOUT_REMOTE_WEBHOOK_TOKEN"
DEMO_WEBHOOK_HMAC_ENV = "SCOUT_REMOTE_WEBHOOK_HMAC_SECRET"
DEMO_PRIMARY_TARGET_ENV = "SCOUT_REMOTE_PRIMARY_TARGET_REF"
DEMO_BACKUP_TARGET_ENV = "SCOUT_REMOTE_BACKUP_TARGET_REF"


class RuntimeRemoteProviderDemoBundleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["runtime_remote_provider_local_webhook_demo_bundle"] = (
        "runtime_remote_provider_local_webhook_demo_bundle"
    )
    status: Literal["ready"] = "ready"
    output_dir: str
    provider_config_path: str
    send_intent_path: str
    payload_preview_path: str
    operator_command_path: str
    demo_env_path: str
    webhook_url: str
    localhost_only: Literal[True] = True
    external_network_allowed: Literal[False] = False
    provider_config_status: str
    payload_preview_status: str
    send_intent_status: str
    raw_payloads_embedded: Literal[False] = False
    remote_notification_send_count: Literal[0] = 0
    incident_bridge_enable_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


class RuntimeRemoteProviderExternalDemoBundleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["runtime_remote_provider_external_webhook_demo_bundle"] = (
        "runtime_remote_provider_external_webhook_demo_bundle"
    )
    status: Literal["ready_requires_manual_send", "blocked_missing_secret_refs"]
    output_dir: str
    provider_config_path: str
    send_intent_path: str
    payload_preview_path: str
    operator_command_path: str
    secret_refs_path: str
    localhost_only: Literal[False] = False
    external_network_allowed: Literal[True] = True
    provider_config_status: str
    payload_preview_status: str
    send_intent_status: str
    required_secret_refs: list[str]
    missing_secret_refs: list[str]
    secret_values_embedded: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    remote_notification_send_count: Literal[0] = 0
    incident_bridge_enable_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def build_local_webhook_demo_bundle(
    output_dir: Path | str,
    webhook_url: str,
    *,
    operator_id: str = "operator.demo.local",
) -> RuntimeRemoteProviderDemoBundleSummary:
    _require_localhost_webhook_url(webhook_url)
    bundle_dir = Path(output_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    policy = build_webhook_remote_provider_policy_contract()
    config = build_webhook_remote_provider_config_template(policy)
    preflight = run_runtime_remote_provider_config_preflight(
        policy,
        config,
        available_secret_refs=set(config.required_secret_refs()),
    )
    payload_request = RuntimeRemoteProviderPayloadRequest(
        message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
        recipient_ref="remote_contact.primary",
        body_summary=(
            "Local webhook demo: Scout runtime remote provider can send a "
            "reviewed remote status to a localhost capture harness."
        ),
        operator_id=operator_id,
        correlation_refs=[
            "phase4_5.runtime_remote_provider_demo.local_webhook.v0",
            "demo_bundle.localhost_only.v0",
        ],
    )
    payload_preview = compose_runtime_remote_provider_payload(
        policy,
        config,
        preflight,
        payload_request,
    )
    send_intent = queue_runtime_remote_provider_send_intent(
        payload_preview,
        intent_id="remote_provider_send_intent.local_webhook_demo.remote_status.v0",
        queued_by_operator_id=operator_id,
        queued_at_iso="2026-05-20T00:00:00+08:00",
    )

    provider_config_path = bundle_dir / "provider_config.json"
    send_intent_path = bundle_dir / "send_intent.json"
    payload_preview_path = bundle_dir / "payload_preview.json"
    operator_command_path = bundle_dir / "operator_command.txt"
    demo_env_path = bundle_dir / "demo_env.json"
    result_path = bundle_dir / "live_send_result.json"

    provider_config_path.write_text(config.to_json(), encoding="utf-8")
    send_intent_path.write_text(send_intent.to_json(), encoding="utf-8")
    payload_preview_path.write_text(
        _json_dump(payload_preview.model_dump(mode="json")),
        encoding="utf-8",
    )
    demo_env = _build_demo_env_payload(
        webhook_url=webhook_url,
        required_secret_refs=config.required_secret_refs(),
    )
    demo_env_path.write_text(_json_dump(demo_env), encoding="utf-8")
    operator_command_path.write_text(
        _build_operator_command(
            config_path=provider_config_path,
            intent_path=send_intent_path,
            output_path=result_path,
            env=demo_env["env"],
        ),
        encoding="utf-8",
    )

    summary = RuntimeRemoteProviderDemoBundleSummary(
        output_dir=str(bundle_dir),
        provider_config_path=str(provider_config_path),
        send_intent_path=str(send_intent_path),
        payload_preview_path=str(payload_preview_path),
        operator_command_path=str(operator_command_path),
        demo_env_path=str(demo_env_path),
        webhook_url=webhook_url,
        provider_config_status=str(preflight.status),
        payload_preview_status=str(payload_preview.status),
        send_intent_status=str(send_intent.status),
    )
    (bundle_dir / "demo_summary.json").write_text(summary.to_json(), encoding="utf-8")
    return summary


def build_external_webhook_demo_bundle(
    output_dir: Path | str,
    *,
    operator_id: str = "operator.demo.external",
    endpoint_url_secret_ref: str = "env:SCOUT_REMOTE_WEBHOOK_URL",
    auth_secret_ref: str = "env:SCOUT_REMOTE_WEBHOOK_TOKEN",
    signature_secret_ref: str | None = "env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET",
    primary_target_secret_ref: str = "env:SCOUT_REMOTE_PRIMARY_TARGET_REF",
    backup_target_secret_ref: str = "env:SCOUT_REMOTE_BACKUP_TARGET_REF",
    available_secret_refs: set[str] | None = None,
) -> RuntimeRemoteProviderExternalDemoBundleSummary:
    bundle_dir = Path(output_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    policy = build_webhook_remote_provider_policy_contract()
    base_config = build_webhook_remote_provider_config_template(policy)
    config = base_config.model_copy(
        update={
            "endpoint": RuntimeRemoteProviderEndpointConfig(
                endpoint_ref=base_config.endpoint.endpoint_ref,
                endpoint_url_secret_ref=endpoint_url_secret_ref,
            ),
            "auth": RuntimeRemoteProviderAuthConfig(
                auth_secret_ref=auth_secret_ref,
                signature_secret_ref=signature_secret_ref,
            ),
            "recipients": [
                RuntimeRemoteRecipientBinding(
                    recipient_ref="remote_contact.primary",
                    delivery_target_secret_ref=primary_target_secret_ref,
                ),
                RuntimeRemoteRecipientBinding(
                    recipient_ref="remote_contact.backup",
                    delivery_target_secret_ref=backup_target_secret_ref,
                ),
            ],
        }
    )
    preflight = run_runtime_remote_provider_config_preflight(
        policy,
        config,
        available_secret_refs=available_secret_refs or set(),
    )
    payload_request = RuntimeRemoteProviderPayloadRequest(
        message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
        recipient_ref="remote_contact.primary",
        body_summary=(
            "External webhook demo: Scout can send a reviewed remote status to "
            "an operator-provided webhook provider after manual authorization."
        ),
        operator_id=operator_id,
        correlation_refs=[
            "phase4_5.runtime_remote_provider_demo.external_webhook.v0",
            "demo_bundle.operator_secret_refs_only.v0",
        ],
    )
    payload_preview = compose_runtime_remote_provider_payload(
        policy,
        config,
        preflight,
        payload_request,
    )
    send_intent = queue_runtime_remote_provider_send_intent(
        payload_preview,
        intent_id="remote_provider_send_intent.external_webhook_demo.remote_status.v0",
        queued_by_operator_id=operator_id,
        queued_at_iso="2026-05-20T00:00:00+08:00",
    )

    provider_config_path = bundle_dir / "provider_config.json"
    send_intent_path = bundle_dir / "send_intent.json"
    payload_preview_path = bundle_dir / "payload_preview.json"
    operator_command_path = bundle_dir / "operator_command.txt"
    secret_refs_path = bundle_dir / "secret_refs.json"
    result_path = bundle_dir / "live_send_result.json"

    provider_config_path.write_text(config.to_json(), encoding="utf-8")
    send_intent_path.write_text(send_intent.to_json(), encoding="utf-8")
    payload_preview_path.write_text(
        _json_dump(payload_preview.model_dump(mode="json")),
        encoding="utf-8",
    )
    secret_refs_path.write_text(
        _json_dump(_build_external_secret_refs_payload(config.required_secret_refs())),
        encoding="utf-8",
    )
    operator_command_path.write_text(
        _build_external_operator_command(
            config_path=provider_config_path,
            intent_path=send_intent_path,
            output_path=result_path,
            required_secret_refs=config.required_secret_refs(),
        ),
        encoding="utf-8",
    )

    summary = RuntimeRemoteProviderExternalDemoBundleSummary(
        status=(
            "ready_requires_manual_send"
            if preflight.provider_config_ready
            else "blocked_missing_secret_refs"
        ),
        output_dir=str(bundle_dir),
        provider_config_path=str(provider_config_path),
        send_intent_path=str(send_intent_path),
        payload_preview_path=str(payload_preview_path),
        operator_command_path=str(operator_command_path),
        secret_refs_path=str(secret_refs_path),
        provider_config_status=str(preflight.status),
        payload_preview_status=str(payload_preview.status),
        send_intent_status=str(send_intent.status),
        required_secret_refs=config.required_secret_refs(),
        missing_secret_refs=preflight.missing_secret_refs,
    )
    (bundle_dir / "demo_summary.json").write_text(summary.to_json(), encoding="utf-8")
    return summary


def _build_demo_env_payload(
    *, webhook_url: str, required_secret_refs: list[str]
) -> dict[str, object]:
    return {
        "artifact_kind": "runtime_remote_provider_local_webhook_demo_env",
        "status": "ready",
        "localhost_only": True,
        "external_network_allowed": False,
        "webhook_url": webhook_url,
        "required_secret_refs": required_secret_refs,
        "env": {
            DEMO_WEBHOOK_URL_ENV: webhook_url,
            DEMO_WEBHOOK_TOKEN_ENV: "demo-local-provider-token",
            DEMO_WEBHOOK_HMAC_ENV: "demo-local-hmac-secret",
            DEMO_PRIMARY_TARGET_ENV: "demo-primary-contact-target",
            DEMO_BACKUP_TARGET_ENV: "demo-backup-contact-target",
        },
        "boundary": {
            "phase1_incident_bridge_enabled": False,
            "phase2_writeback_allowed": False,
            "raw_payloads_embedded": False,
            "real_external_endpoint_allowed": False,
        },
    }


def _build_external_secret_refs_payload(required_secret_refs: list[str]) -> dict[str, object]:
    return {
        "artifact_kind": "runtime_remote_provider_external_webhook_secret_refs",
        "status": "operator_values_required",
        "required_secret_refs": required_secret_refs,
        "secret_values_embedded": False,
        "raw_endpoint_url_embedded": False,
        "token_value_embedded": False,
        "external_network_allowed_after_manual_authorization": True,
        "boundary": {
            "external_network_allowed_after_manual_authorization": True,
            "phase1_incident_bridge_enabled": False,
            "phase2_writeback_allowed": False,
            "raw_payloads_embedded": False,
        },
        "operator_notes": [
            "Provide secret values through env, file, or keychain refs before running the command.",
            "Do not edit provider_config.json to embed raw endpoint URLs or token values.",
        ],
    }


def _build_operator_command(
    *,
    config_path: Path,
    intent_path: Path,
    output_path: Path,
    env: dict[str, str],
) -> str:
    env_prefix = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in sorted(env.items())
    )
    command = [
        "./venv/bin/python",
        "runtime_remote_provider_live_send_cli.py",
        "--config",
        str(config_path),
        "--intent",
        str(intent_path),
        "--output",
        str(output_path),
        "--enable-provider-adapter",
        "--enable-live-network-send",
        "--authorize-manual-send",
    ]
    return env_prefix + " " + " ".join(shlex.quote(part) for part in command) + "\n"


def _build_external_operator_command(
    *,
    config_path: Path,
    intent_path: Path,
    output_path: Path,
    required_secret_refs: list[str],
) -> str:
    env_exports = [
        _placeholder_export(secret_ref)
        for secret_ref in required_secret_refs
        if secret_ref.startswith("env:")
    ]
    command = [
        "./venv/bin/python",
        "runtime_remote_provider_live_send_cli.py",
        "--config",
        str(config_path),
        "--intent",
        str(intent_path),
        "--output",
        str(output_path),
        "--enable-provider-adapter",
        "--enable-live-network-send",
        "--authorize-manual-send",
    ]
    return (
        "\n".join(env_exports)
        + "\n"
        + " ".join(shlex.quote(part) for part in command)
        + "\n"
    )


def _placeholder_export(secret_ref: str) -> str:
    env_name = secret_ref.removeprefix("env:")
    return f"export {env_name}=<operator-provided-secret>"


def _require_localhost_webhook_url(webhook_url: str) -> None:
    parsed = urlparse(webhook_url)
    if parsed.scheme != "http":
        raise ValueError("local webhook demo URL must use http")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("local webhook demo URL must not include auth or fragment")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("local webhook demo URL must point to localhost")
    if not parsed.path or parsed.path == "/":
        raise ValueError("local webhook demo URL must include a capture path")


def _json_dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
