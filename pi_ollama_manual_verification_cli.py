from __future__ import annotations

import argparse
from pathlib import Path

from pi_ollama_manual_verification import (
    format_pi_ollama_manual_verification_summary,
    load_pi_ollama_manual_verification_index,
    load_pi_ollama_manual_verification_result,
    summarize_pi_ollama_manual_verification_index,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render read-only Pi/Ollama manual verification summaries."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--result", type=Path, help="Manual verification result JSON.")
    mode.add_argument("--index", type=Path, help="Manual verification index JSON.")
    args = parser.parse_args()

    if args.result is not None:
        result = load_pi_ollama_manual_verification_result(args.result)
        print(format_pi_ollama_manual_verification_summary(result))
        return 0

    index = load_pi_ollama_manual_verification_index(args.index)
    print(summarize_pi_ollama_manual_verification_index(index))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
