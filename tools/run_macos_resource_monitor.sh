#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
while [[ -L "${SCRIPT_PATH}" ]]; do
  SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
  SCRIPT_PATH="$(readlink "${SCRIPT_PATH}")"
  if [[ "${SCRIPT_PATH}" != /* ]]; then
    SCRIPT_PATH="${SCRIPT_DIR}/${SCRIPT_PATH}"
  fi
done
ROOT="$(cd "$(dirname "${SCRIPT_PATH}")/.." && pwd)"
PYTHON="${SCOUT_MONITOR_PYTHON:-${ROOT}/venv/bin/python}"

if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3 || true)"
fi

if [[ -z "${PYTHON}" || ! -x "${PYTHON}" ]]; then
  printf '%s\n' \
    "Scout macOS resource monitor needs Python 3.12+." \
    "Set SCOUT_MONITOR_PYTHON to an executable Python or create ${ROOT}/venv."
  exit 2
fi

exec "${PYTHON}" "${ROOT}/tools/macos_resource_monitor.py" "$@"
