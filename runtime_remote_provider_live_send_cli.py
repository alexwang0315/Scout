from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence, Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime_remote_provider_config_preflight import RuntimeRemoteProviderConfig
from runtime_remote_provider_live_adapter import (
    RuntimeRemoteProviderLiveSendOptions,
    RuntimeRemoteProviderLiveSendResult,
    RuntimeRemoteSecretResolver,
    RuntimeRemoteWebhookHttpRequest,
    send_runtime_remote_provider_webhook_intent,
)
from runtime_remote_provider_policy import RuntimeRemoteProviderKind
from runtime_remote_provider_send_queue import RuntimeRemoteProviderSendIntent


class RuntimeRemoteProviderLiveSendCliModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeRemoteProviderOperatorBlockedResult(RuntimeRemoteProviderLiveSendCliModel):
    artifact_kind: Literal["runtime_remote_provider_operator_request_result"] = (
        "runtime_remote_provider_operator_request_result"
    )
    status: Literal["operator_request_blocked"] = "operator_request_blocked"
    provider_id: str | None = None
    provider_kind: RuntimeRemoteProviderKind | None = None
    config_path: str
    intent_path: str
    output_path: str | None = None
    blocker_count: int = 0
    blocker_reasons: list[str] = Field(default_factory=list)
    live_network_send_attempted: Literal[False] = False
    send_performed: Literal[False] = False
    remote_notification_send_count: Literal[0] = 0
    summary_only: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    raw_secret_values_embedded: Literal[False] = False
    endpoint_url_embedded: Literal[False] = False
    token_value_embedded: Literal[False] = False
    incident_bridge_enable_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def run_runtime_remote_provider_live_send_cli(
    argv: Sequence[str] | None = None,
    *,
    resolver: RuntimeRemoteSecretResolver | None = None,
    transport: Callable[[RuntimeRemoteWebhookHttpRequest], Any] | None = None,
) -> tuple[int, RuntimeRemoteProviderLiveSendResult | RuntimeRemoteProviderOperatorBlockedResult]:
    args = _build_parser().parse_args(argv)
    config_path = Path(args.config)
    intent_path = Path(args.intent)
    output_path = Path(args.output) if args.output else None

    artifact_blockers = []
    if not config_path.exists():
        artifact_blockers.append("missing_config_artifact")
    if not intent_path.exists():
        artifact_blockers.append("missing_send_intent_artifact")
    if artifact_blockers:
        result = RuntimeRemoteProviderOperatorBlockedResult(
            config_path=str(config_path),
            intent_path=str(intent_path),
            output_path=str(output_path) if output_path else None,
            blocker_count=len(artifact_blockers),
            blocker_reasons=artifact_blockers,
        )
        _write_or_print_result(result, output_path)
        return 2, result

    config = RuntimeRemoteProviderConfig.model_validate_json(
        config_path.read_text(encoding="utf-8")
    )
    send_intent = RuntimeRemoteProviderSendIntent.model_validate_json(
        intent_path.read_text(encoding="utf-8")
    )
    result = send_runtime_remote_provider_webhook_intent(
        config,
        send_intent,
        options=RuntimeRemoteProviderLiveSendOptions(
            provider_adapter_enabled=args.enable_provider_adapter,
            live_network_send_enabled=args.enable_live_network_send,
            manual_send_authorization=args.authorize_manual_send,
            timeout_seconds=args.timeout_seconds,
        ),
        resolver=resolver,
        transport=transport,
    )
    _write_or_print_result(result, output_path)
    return (0 if result.status == "sent" else 2), result


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, _ = run_runtime_remote_provider_live_send_cli(argv)
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Trigger a reviewed runtime remote provider send intent. Defaults to "
            "blocked unless all live-send flags are present."
        )
    )
    parser.add_argument("--config", required=True, help="Provider config artifact JSON.")
    parser.add_argument("--intent", required=True, help="Queued send intent artifact JSON.")
    parser.add_argument("--output", help="Optional JSON result output path.")
    parser.add_argument(
        "--enable-provider-adapter",
        action="store_true",
        help="Enable provider adapter execution for this invocation.",
    )
    parser.add_argument(
        "--enable-live-network-send",
        action="store_true",
        help="Allow this invocation to perform a live network send.",
    )
    parser.add_argument(
        "--authorize-manual-send",
        action="store_true",
        help="Record operator manual authorization for this send.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=10.0,
        help="HTTP timeout for the live provider request.",
    )
    return parser


def _write_or_print_result(
    result: RuntimeRemoteProviderLiveSendResult | RuntimeRemoteProviderOperatorBlockedResult,
    output_path: Path | None,
) -> None:
    payload = result.to_json()
    if output_path is None:
        sys.stdout.write(payload)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
