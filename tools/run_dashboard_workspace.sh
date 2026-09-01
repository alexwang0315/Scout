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

exec "${PYTHON}" "${ROOT}/tools/dashboard_workspace_app.py" "$@"
