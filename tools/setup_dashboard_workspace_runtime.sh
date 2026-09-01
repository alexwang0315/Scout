#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_ROOT="${SCOUT_DASHBOARD_VENV:-${ROOT}/venv}"
DEFAULT_PYTHON="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
BOOTSTRAP_PYTHON="${SCOUT_BOOTSTRAP_PYTHON:-${DEFAULT_PYTHON}}"
OSMIUM_BIN_DIR="${SCOUT_OSMIUM_BIN_DIR:-${HOME}/.local/share/scout-tools/micromamba/envs/scout-osmium/bin}"
OSMIUM_CLI="${OSMIUM_BIN_DIR}/osmium"
GRASS_PREFIX="${SCOUT_GRASS_PREFIX:-${HOME}/.local/share/scout-tools/micromamba/envs/scout-grass}"
GRASS_CLI="${SCOUT_GRASS_CLI:-${GRASS_PREFIX}/bin/grass}"
GRASS_VERSION="${SCOUT_GRASS_VERSION:-8.5.0}"
MICROMAMBA="${SCOUT_MICROMAMBA:-${HOME}/.local/bin/micromamba}"
USER_BIN_DIR="${SCOUT_USER_BIN_DIR:-${HOME}/.local/bin}"
QGIS_WORKER_TOKEN_FILE="${SCOUT_QGIS_WORKER_TOKEN_FILE:-${HOME}/.scout-fusion/qgis-desktop/runtime/worker-token}"
RUNTIME_MARKER="${VENV_ROOT}/.scout-dashboard-runtime-pyproject.sha256"
PYPROJECT_HASH="$(LC_ALL=C shasum -a 256 "${ROOT}/pyproject.toml")"
PYPROJECT_HASH="${PYPROJECT_HASH%% *}"

if [[ ! -x "${BOOTSTRAP_PYTHON}" ]]; then
  BOOTSTRAP_PYTHON="$(command -v python3)"
fi

if [[ ! -x "${VENV_ROOT}/bin/python" ]]; then
  "${BOOTSTRAP_PYTHON}" -m venv "${VENV_ROOT}"
fi

RUNTIME_READY=0
if [[ -f "${RUNTIME_MARKER}" ]] \
  && [[ "$(<"${RUNTIME_MARKER}")" == "${PYPROJECT_HASH}" ]] \
  && "${VENV_ROOT}/bin/python" -c 'import fastapi, osmium, uvicorn' >/dev/null 2>&1; then
  RUNTIME_READY=1
fi

if [[ "${RUNTIME_READY}" -eq 0 ]]; then
  "${VENV_ROOT}/bin/python" -m pip install -e "${ROOT}[pretrip-workstation]"
  "${VENV_ROOT}/bin/python" -c 'import fastapi, osmium, uvicorn'
  printf '%s\n' "${PYPROJECT_HASH}" > "${RUNTIME_MARKER}"
else
  printf '%s\n' "Dashboard Python runtime already ready; package install skipped."
fi

if [[ ! -x "${OSMIUM_CLI}" ]]; then
  printf '%s\n' \
    "OSM PBF command-line parser is missing: ${OSMIUM_CLI}" \
    "Restore the persistent scout-osmium environment before running preparation."
  exit 2
fi

if [[ ! -x "${GRASS_CLI}" ]]; then
  if [[ ! -x "${MICROMAMBA}" ]]; then
    printf '%s\n' \
      "GRASS GIS runtime is missing: ${GRASS_CLI}" \
      "micromamba is also unavailable: ${MICROMAMBA}"
    exit 2
  fi
  "${MICROMAMBA}" create \
    --yes \
    --prefix "${GRASS_PREFIX}" \
    --channel conda-forge \
    "grass=${GRASS_VERSION}"
fi

mkdir -p "${USER_BIN_DIR}"
if [[ ! -s "${QGIS_WORKER_TOKEN_FILE}" ]]; then
  mkdir -p "$(dirname "${QGIS_WORKER_TOKEN_FILE}")"
  token_tmp="${QGIS_WORKER_TOKEN_FILE}.tmp.$$"
  (umask 077; "${VENV_ROOT}/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))' > "${token_tmp}")
  mv "${token_tmp}" "${QGIS_WORKER_TOKEN_FILE}"
fi
chmod 600 "${QGIS_WORKER_TOKEN_FILE}"
ln -sfn "${OSMIUM_CLI}" "${VENV_ROOT}/bin/osmium"
ln -sfn "${OSMIUM_CLI}" "${USER_BIN_DIR}/osmium"
ln -sfn "${GRASS_CLI}" "${VENV_ROOT}/bin/grass"
ln -sfn "${GRASS_CLI}" "${USER_BIN_DIR}/grass"
ln -sfn "${ROOT}/tools/run_dashboard_workspace.sh" "${USER_BIN_DIR}/scout-dashboard"
ln -sfn "${ROOT}/tools/run_qgis_worker.sh" "${USER_BIN_DIR}/scout-qgis-worker"

"${VENV_ROOT}/bin/python" -c \
  'import fastapi, osmium, uvicorn; print("dashboard runtime ready")'
"${VENV_ROOT}/bin/osmium" --version
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 "${VENV_ROOT}/bin/grass" --version
printf '%s\n' \
  "Dashboard shortcut ready: ${USER_BIN_DIR}/scout-dashboard" \
  "QGIS worker shortcut ready: ${USER_BIN_DIR}/scout-qgis-worker" \
  "OSM parser shortcut ready: ${USER_BIN_DIR}/osmium" \
  "GRASS GIS shortcut ready: ${USER_BIN_DIR}/grass"
