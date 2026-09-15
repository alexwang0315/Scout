#!/usr/bin/env python3
"""Run the optional portal backport checks in explicit isolated child processes."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--junitxml", type=Path)
    args = parser.parse_args()
    target = args.target.resolve(strict=True)
    if not (target / "starlette" / "testclient.py").is_file():
        parser.error("--target must contain the installed Starlette overlay")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(target) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    fresh = subprocess.run(
        [sys.executable, "-B", "-W", "error", str(ROOT / "fresh_import.py"), str(target)],
        env=env,
        check=False,
    )
    if fresh.returncode:
        return fresh.returncode
    command = [
        sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "-W", "error", str(ROOT / "compatibility_cases.py"),
    ]
    if args.junitxml:
        command.append("--junitxml=" + str(args.junitxml.resolve()))
    return subprocess.run(command, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
