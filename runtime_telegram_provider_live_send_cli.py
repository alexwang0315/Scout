from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from runtime_telegram_provider_live_adapter import (
    TelegramHttpRequest,
    TelegramProviderLiveSendOptions,
    TelegramProviderSendIntent,
    send_telegram_provider_intent,
)


def run_telegram_provider_live_send_cli(
    argv: Sequence[str] | None = None,
    *,
    transport: Callable[[TelegramHttpRequest], Any] | None = None,
) -> tuple[int, object]:
    args = _build_parser().parse_args(argv)
    intent_path = Path(args.intent)
    output_path = Path(args.output) if args.output else None

    send_intent = TelegramProviderSendIntent.model_validate_json(
        intent_path.read_text(encoding="utf-8")
    )
    result = send_telegram_provider_intent(
        send_intent,
        options=TelegramProviderLiveSendOptions(
            provider_adapter_enabled=args.enable_provider_adapter,
            live_network_send_enabled=args.enable_live_network_send,
            manual_send_authorization=args.authorize_manual_send,
            timeout_seconds=args.timeout_seconds,
        ),
        transport=transport,
    )
    payload = result.to_json()
    if output_path is None:
        sys.stdout.write(payload)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
    return (0 if result.status == "sent" else 2), result


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, _ = run_telegram_provider_live_send_cli(argv)
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Trigger a reviewed Telegram provider send intent. Defaults to "
            "blocked unless all live-send flags are present."
        )
    )
    parser.add_argument("--intent", required=True, help="Telegram send intent JSON.")
    parser.add_argument("--output", help="Optional JSON result output path.")
    parser.add_argument("--enable-provider-adapter", action="store_true")
    parser.add_argument("--enable-live-network-send", action="store_true")
    parser.add_argument("--authorize-manual-send", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
