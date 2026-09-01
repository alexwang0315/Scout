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
QGIS_CONTENTS="${SCOUT_QGIS_CONTENTS:-/Applications/QGIS-LTR.app/Contents}"
QGIS_WORKER_TOKEN_FILE="${SCOUT_QGIS_WORKER_TOKEN_FILE:-${HOME}/.scout-fusion/qgis-desktop/runtime/worker-token}"
QGIS_MCP_CONNECTION_FILE="${QGIS_MCP_CONNECTION_FILE:-${HOME}/.qgis-mcp/connection.json}"
QGIS_MCP_SERVER_ROOT="${SCOUT_QGIS_MCP_PYTHONPATH:-${HOME}/.scout-fusion/qgis-desktop/profiles/scout/python/plugins/qgis_agent_mcp/_server}"
WORKER_HOST="${SCOUT_QGIS_WORKER_HOST:-127.0.0.1}"
WORKER_PORT="${SCOUT_QGIS_WORKER_PORT:-9876}"

if [[ "${WORKER_HOST}" != "127.0.0.1" && "${WORKER_HOST}" != "localhost" ]]; then
  printf '%s\n' "QGIS worker must bind to a loopback host."
  exit 2
fi
if [[ ! -x "${PYTHON}" ]]; then
  printf '%s\n' "Dashboard runtime is missing. Run tools/setup_dashboard_workspace_runtime.sh once."
  exit 2
fi
if [[ ! -s "${QGIS_WORKER_TOKEN_FILE}" ]]; then
  printf '%s\n' "QGIS worker token is missing. Run tools/setup_dashboard_workspace_runtime.sh once."
  exit 2
fi
if [[ ! -f "${QGIS_MCP_CONNECTION_FILE}" ]]; then
  printf '%s\n' "QGIS MCP connection file is missing. Start the Scout QGIS profile first."
  exit 2
fi
if [[ ! -d "${QGIS_MCP_SERVER_ROOT}" ]]; then
  printf '%s\n' "QGIS MCP server package is missing from the Scout QGIS profile."
  exit 2
fi

export PATH="${VENV_ROOT}/bin:${HOME}/.local/bin:${PATH}"
export PYTHONPATH="${ROOT}"
export LANG="${SCOUT_GIS_LOCALE:-en_US.UTF-8}"
export LC_ALL="${SCOUT_GIS_LOCALE:-en_US.UTF-8}"
export QGIS_MCP_CONNECTION_FILE
export SCOUT_QGIS_WORKER_ENABLED="${SCOUT_QGIS_WORKER_ENABLED:-true}"
export SCOUT_QGIS_WORKER_TOKEN="$(<"${QGIS_WORKER_TOKEN_FILE}")"
export SCOUT_QGIS_SOURCE_ROOTS="${SCOUT_QGIS_SOURCE_ROOTS:-${HOME}/workspace}"
export SCOUT_QGIS_WORKER_TIMEOUT="${SCOUT_QGIS_WORKER_TIMEOUT:-1800}"
export SCOUT_QGIS_WORKER_POLL_INTERVAL="${SCOUT_QGIS_WORKER_POLL_INTERVAL:-0.25}"
export SCOUT_QGIS_MCP_PYTHONPATH="${QGIS_MCP_SERVER_ROOT}"
export SCOUT_QGIS_MCP_COMMAND_JSON="${SCOUT_QGIS_MCP_COMMAND_JSON:-[\"${PYTHON}\",\"-m\",\"qgis_mcp\"]}"
if [[ -d "${QGIS_CONTENTS}/Resources/qgis/gdal" ]]; then
  export GDAL_DATA="${GDAL_DATA:-${QGIS_CONTENTS}/Resources/qgis/gdal}"
fi
if [[ -d "${QGIS_CONTENTS}/Resources/qgis/proj" ]]; then
  export PROJ_LIB="${PROJ_LIB:-${QGIS_CONTENTS}/Resources/qgis/proj}"
fi

exec "${PYTHON}" -m uvicorn qgis_worker:create_qgis_worker_app --factory \
  --host "${WORKER_HOST}" --port "${WORKER_PORT}" --log-level warning
