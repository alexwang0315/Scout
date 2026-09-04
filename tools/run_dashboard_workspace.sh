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
VENV_ROOT="${SCOUT_DASHBOARD_VENV:-${ROOT}/venv}"
PYTHON="${VENV_ROOT}/bin/python"
OSMIUM_CLI="${VENV_ROOT}/bin/osmium"
GRASS_CLI="${VENV_ROOT}/bin/grass"
QGIS_CONTENTS="${SCOUT_QGIS_CONTENTS:-/Applications/QGIS-LTR.app/Contents}"
QGIS_WORKER_TOKEN_FILE="${SCOUT_QGIS_WORKER_TOKEN_FILE:-${HOME}/.scout-fusion/qgis-desktop/runtime/worker-token}"
QGIS_WORKER_URL="${SCOUT_QGIS_WORKER_URL:-http://127.0.0.1:9876}"
QGIS_WORKER_LAUNCHER="${SCOUT_DASHBOARD_QGIS_WORKER_LAUNCHER:-${ROOT}/tools/run_qgis_worker.sh}"
QGIS_WORKER_LOG="${SCOUT_DASHBOARD_QGIS_WORKER_LOG:-${HOME}/.scout-fusion/qgis-desktop/runtime/qgis-worker.log}"
AUTO_QGIS_WORKER="${SCOUT_DASHBOARD_AUTO_QGIS_WORKER:-true}"
QGIS_WORKER_REQUIRED="${SCOUT_DASHBOARD_QGIS_WORKER_REQUIRED:-false}"
QGIS_WORKER_START_TIMEOUT="${SCOUT_DASHBOARD_QGIS_WORKER_START_TIMEOUT:-15}"
MANAGED_QGIS_WORKER_PID=""
DASHBOARD_PID=""

case "${AUTO_QGIS_WORKER}:${QGIS_WORKER_REQUIRED}" in
  true:true|true:false|false:true|false:false) ;;
  *)
    printf '%s\n' \
      "SCOUT_DASHBOARD_AUTO_QGIS_WORKER and SCOUT_DASHBOARD_QGIS_WORKER_REQUIRED must be true or false."
    exit 2
    ;;
esac
case "${QGIS_WORKER_START_TIMEOUT}" in
  ''|*[!0-9]*|0)
    printf '%s\n' "SCOUT_DASHBOARD_QGIS_WORKER_START_TIMEOUT must be a positive integer."
    exit 2
    ;;
esac

qgis_worker_responding() {
  "${PYTHON}" - <<'PY' >/dev/null 2>&1
import json
import os
import urllib.request

base_url = os.environ["SCOUT_QGIS_WORKER_URL"].rstrip("/")
token = os.environ["SCOUT_QGIS_WORKER_TOKEN"]
request = urllib.request.Request(
    f"{base_url}/capabilities",
    headers={"Authorization": f"Bearer {token}"},
)
try:
    with urllib.request.urlopen(request, timeout=1.0) as response:
        payload = json.load(response)
except Exception:
    raise SystemExit(1)
raise SystemExit(
    0
    if payload.get("schema_version") == "scout_qgis_worker_capabilities.v0_1"
    else 1
)
PY
}

qgis_worker_url_is_local() {
  case "${QGIS_WORKER_URL}" in
    http://127.0.0.1:*|http://localhost:*) return 0 ;;
    *) return 1 ;;
  esac
}

stop_managed_children() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ -n "${DASHBOARD_PID}" ]] && kill -0 "${DASHBOARD_PID}" 2>/dev/null; then
    kill "${DASHBOARD_PID}" 2>/dev/null || true
    wait "${DASHBOARD_PID}" 2>/dev/null || true
  fi
  if [[ -n "${MANAGED_QGIS_WORKER_PID}" ]] && kill -0 "${MANAGED_QGIS_WORKER_PID}" 2>/dev/null; then
    kill "${MANAGED_QGIS_WORKER_PID}" 2>/dev/null || true
    wait "${MANAGED_QGIS_WORKER_PID}" 2>/dev/null || true
  fi
  exit "${exit_code}"
}

start_qgis_worker_if_needed() {
  if [[ -z "${SCOUT_QGIS_WORKER_TOKEN:-}" ]]; then
    printf '%s\n' "QGIS worker autostart skipped: persistent worker token is unavailable."
    [[ "${QGIS_WORKER_REQUIRED}" == "false" ]]
    return
  fi
  if qgis_worker_responding; then
    printf '%s\n' "Reusing QGIS worker at ${QGIS_WORKER_URL}."
    return 0
  fi
  if [[ "${AUTO_QGIS_WORKER}" == "false" ]]; then
    printf '%s\n' "QGIS worker autostart is disabled; Dashboard will report its live availability."
    [[ "${QGIS_WORKER_REQUIRED}" == "false" ]]
    return
  fi
  if ! qgis_worker_url_is_local; then
    printf '%s\n' "QGIS worker autostart is local-only; Dashboard will use the configured remote endpoint if it becomes available."
    [[ "${QGIS_WORKER_REQUIRED}" == "false" ]]
    return
  fi
  if [[ ! -x "${QGIS_WORKER_LAUNCHER}" ]]; then
    printf '%s\n' "QGIS worker launcher is unavailable: ${QGIS_WORKER_LAUNCHER}"
    [[ "${QGIS_WORKER_REQUIRED}" == "false" ]]
    return
  fi

  mkdir -p "$(dirname "${QGIS_WORKER_LOG}")"
  "${QGIS_WORKER_LAUNCHER}" >>"${QGIS_WORKER_LOG}" 2>&1 &
  MANAGED_QGIS_WORKER_PID=$!
  local deadline=$((SECONDS + QGIS_WORKER_START_TIMEOUT))
  while (( SECONDS <= deadline )); do
    if qgis_worker_responding; then
      printf '%s\n' "QGIS worker started with Dashboard at ${QGIS_WORKER_URL}."
      return 0
    fi
    if ! kill -0 "${MANAGED_QGIS_WORKER_PID}" 2>/dev/null; then
      break
    fi
    sleep 0.25
  done

  printf '%s\n' \
    "QGIS worker did not become ready; Dashboard will remain available and TRH will fail closed." \
    "Worker log: ${QGIS_WORKER_LOG}"
  if kill -0 "${MANAGED_QGIS_WORKER_PID}" 2>/dev/null; then
    kill "${MANAGED_QGIS_WORKER_PID}" 2>/dev/null || true
    wait "${MANAGED_QGIS_WORKER_PID}" 2>/dev/null || true
  fi
  MANAGED_QGIS_WORKER_PID=""
  [[ "${QGIS_WORKER_REQUIRED}" == "false" ]]
}

if [[ ! -x "${PYTHON}" ]]; then
  printf '%s\n' \
    "Dashboard runtime is missing." \
    "Run tools/setup_dashboard_workspace_runtime.sh once."
  exit 2
fi

if ! "${PYTHON}" -c 'import fastapi, osmium, uvicorn' >/dev/null 2>&1; then
  printf '%s\n' \
    "Dashboard runtime is incomplete." \
    "Run tools/setup_dashboard_workspace_runtime.sh once."
  exit 2
fi

if [[ ! -x "${OSMIUM_CLI}" ]]; then
  printf '%s\n' \
    "Dashboard OSM parser shortcut is missing." \
    "Run tools/setup_dashboard_workspace_runtime.sh once."
  exit 2
fi

if [[ ! -x "${GRASS_CLI}" ]]; then
  printf '%s\n' \
    "Dashboard GRASS GIS shortcut is missing." \
    "Run tools/setup_dashboard_workspace_runtime.sh once."
  exit 2
fi

export PATH="${VENV_ROOT}/bin:${PATH}"
export LANG="${SCOUT_GIS_LOCALE:-en_US.UTF-8}"
export LC_ALL="${SCOUT_GIS_LOCALE:-en_US.UTF-8}"
export SCOUT_QGIS_TIMEOUT="${SCOUT_QGIS_TIMEOUT:-30}"
if [[ -z "${SCOUT_QGIS_WORKER_TOKEN:-}" && -r "${QGIS_WORKER_TOKEN_FILE}" ]]; then
  export SCOUT_QGIS_WORKER_TOKEN="$(<"${QGIS_WORKER_TOKEN_FILE}")"
fi
if [[ -n "${SCOUT_QGIS_WORKER_TOKEN:-}" ]]; then
  export SCOUT_QGIS_ENABLED="${SCOUT_QGIS_ENABLED:-true}"
  export SCOUT_QGIS_WORKER_URL="${QGIS_WORKER_URL}"
  export SCOUT_QGIS_LOCAL_ENDPOINT_REQUIRED="${SCOUT_QGIS_LOCAL_ENDPOINT_REQUIRED:-true}"
fi
if [[ -d "${QGIS_CONTENTS}/Resources/qgis/gdal" ]]; then
  export GDAL_DATA="${GDAL_DATA:-${QGIS_CONTENTS}/Resources/qgis/gdal}"
fi
if [[ -d "${QGIS_CONTENTS}/Resources/qgis/proj" ]]; then
  export PROJ_LIB="${PROJ_LIB:-${QGIS_CONTENTS}/Resources/qgis/proj}"
fi

trap stop_managed_children EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
start_qgis_worker_if_needed

"${PYTHON}" "${ROOT}/tools/dashboard_workspace_app.py" "$@" &
DASHBOARD_PID=$!
if wait "${DASHBOARD_PID}"; then
  dashboard_status=0
else
  dashboard_status=$?
fi
DASHBOARD_PID=""
exit "${dashboard_status}"
