"""CLI for the Mac Scout AI chat interface."""

from __future__ import annotations

import argparse
import os
import webbrowser

from scout.mac_chat import create_mac_chat_app
from scout.mac_chat.client import DEFAULT_SCOUT_SERVER_URL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Mac Scout AI chat UI against a Scout hardware server."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Mac-local bind host.")
    parser.add_argument("--port", type=int, default=8765, help="Mac-local UI port.")
    parser.add_argument(
        "--target-url",
        default=os.getenv("SCOUT_AI_SERVER_URL", DEFAULT_SCOUT_SERVER_URL),
        help="Scout AI OS server URL on the Scout hardware.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the Mac browser after the local UI starts.",
    )
    args = parser.parse_args(argv)

    import uvicorn

    app = create_mac_chat_app(target_url=args.target_url)
    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        webbrowser.open(url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
