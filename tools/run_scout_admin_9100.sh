#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PORT="${SCOUT_ADMIN_PORT:-9100}"

export SCOUT_DATA_ROOT="${SCOUT_DATA_ROOT:-/data/scout}"
export SCOUT_PRETRIP_WORKSPACE_ROOT="${SCOUT_PRETRIP_WORKSPACE_ROOT:-/data/scout/admin/pretrip-workspaces}"
export SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT="${SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT:-/data/scout/raster-tiles}"
export SCOUT_ADMIN_OSM_TILE_CACHE_ROOT="${SCOUT_ADMIN_OSM_TILE_CACHE_ROOT:-/data/scout/osm-tiles}"
export SCOUT_DEBUG_API_ENABLED="${SCOUT_DEBUG_API_ENABLED:-1}"
export SCOUT_RUNTIME_PROFILE="${SCOUT_RUNTIME_PROFILE:-local-alpha-workspace}"

PYTHON_BIN="${SCOUT_ADMIN_PYTHON:-./.venv/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="${SCOUT_ADMIN_PYTHON:-./venv/bin/python}"
fi

exec "${PYTHON_BIN}" -m uvicorn phase4_admin_runtime:app --host 0.0.0.0 --port "${PORT}"
