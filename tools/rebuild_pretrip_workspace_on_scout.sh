#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${SCOUT_PROJECT_ID:-chilai_nanhua_day1}"
WORKSPACE_ROOT="${SCOUT_PRETRIP_WORKSPACE_ROOT:-/data/scout/admin/pretrip-workspaces}"
MATERIAL_ROOT="${SCOUT_PRETRIP_MATERIAL_ROOT:-/data/scout/materials/pretrip/${PROJECT_ID}}"
MATERIAL_MANIFEST="${MATERIAL_ROOT}/material_manifest.json"
if [[ -z "${SCOUT_SOURCE_GPX_ROOT:-}" && -f "${MATERIAL_MANIFEST}" ]]; then
  SOURCE_GPX_ROOT="$(
    python3 - "${MATERIAL_MANIFEST}" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(manifest.get("sources", {}).get("gpx_corpus", ""))
PY
  )"
else
  SOURCE_GPX_ROOT="${SCOUT_SOURCE_GPX_ROOT:-/data/scout/source-gpx/twmap-gpx-yunhai}"
fi
if [[ -z "${SCOUT_GOLDEN_ROUTE_GPX:-}" && -f "${MATERIAL_MANIFEST}" ]]; then
  GOLDEN_ROUTE_GPX="$(
    python3 - "${MATERIAL_MANIFEST}" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(manifest.get("sources", {}).get("primary_gpx", ""))
PY
  )"
else
  GOLDEN_ROUTE_GPX="${SCOUT_GOLDEN_ROUTE_GPX:-${SOURCE_GPX_ROOT}/能高安東軍縱走.gpx.gpx}"
fi
PYTHON_BIN="${PYTHON_BIN:-./.venv/bin/python}"
ADMIN_BASE_URL="${SCOUT_PRETRIP_ADMIN_BASE_URL:-http://127.0.0.1:9100}"
ADMIN_BEARER_TOKEN_FILE="${SCOUT_ADMIN_BEARER_TOKEN_FILE:-}"
CHECKPOINT_SPACING_M="${SCOUT_CHECKPOINT_SPACING_M:-500}"
MAX_REFERENCE_DISPLAY_POINTS="${SCOUT_MAX_REFERENCE_DISPLAY_POINTS:-2500}"
MAX_REASONABLE_GPX_SPEED_KMH="${SCOUT_MAX_REASONABLE_GPX_SPEED_KMH:-120}"
ROUTE_CORRIDOR_M="${SCOUT_ROUTE_CORRIDOR_M:-500}"
REFERENCE_TRACK_CORRIDOR_M="${SCOUT_REFERENCE_TRACK_CORRIDOR_M:-300}"
BACKUP_ROOT="${SCOUT_PRETRIP_BACKUP_ROOT:-${WORKSPACE_ROOT}}"
LOG_ROOT="${SCOUT_PRETRIP_REBUILD_LOG_ROOT:-/tmp}"
LAYERS="${SCOUT_PRETRIP_LAYERS:-osm,overpass,terrain,risk-score,risk-ribbon,risk-heatmap,risk-delta,imagery,weather,reference-tracks,route,segments,checkpoints,pois,hazards,corridors,retreat,route-notes}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python executable not found or not executable: ${PYTHON_BIN}" >&2
  exit 2
fi

if [[ ! -f "${GOLDEN_ROUTE_GPX}" ]]; then
  echo "Golden route GPX not found: ${GOLDEN_ROUTE_GPX}" >&2
  exit 2
fi

if [[ ! -d "${SOURCE_GPX_ROOT}" ]]; then
  echo "Source GPX root not found: ${SOURCE_GPX_ROOT}" >&2
  exit 2
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PROJECT_ROOT="${WORKSPACE_ROOT}/${PROJECT_ID}"
BACKUP_PATH="${BACKUP_ROOT}/${PROJECT_ID}.backup.${STAMP}"
LOG_PATH="${LOG_ROOT}/scout_pretrip_rebuild_${PROJECT_ID}_${STAMP}.log"

mkdir -p "${WORKSPACE_ROOT}" "${BACKUP_ROOT}" "${LOG_ROOT}"

{
  echo "project_id=${PROJECT_ID}"
  echo "workspace_root=${WORKSPACE_ROOT}"
  echo "material_root=${MATERIAL_ROOT}"
  echo "source_gpx_root=${SOURCE_GPX_ROOT}"
  echo "golden_route_gpx=${GOLDEN_ROUTE_GPX}"
  echo "admin_base_url=${ADMIN_BASE_URL}"
  echo "log_path=${LOG_PATH}"

  if [[ -d "${PROJECT_ROOT}" ]]; then
    echo "Moving existing workspace to ${BACKUP_PATH}"
    mv "${PROJECT_ROOT}" "${BACKUP_PATH}"
  else
    echo "No existing workspace to move."
  fi

  echo "Running pretrip importer..."
  IMPORT_ARGS=(
    -m pretrip_import
    --project-id "${PROJECT_ID}" \
    --golden-route-gpx "${GOLDEN_ROUTE_GPX}" \
    --reference-dir "${SOURCE_GPX_ROOT}" \
    --workspace-root "${WORKSPACE_ROOT}" \
    --profile pi-offline \
    --checkpoint-spacing-m "${CHECKPOINT_SPACING_M}" \
    --max-reference-display-points "${MAX_REFERENCE_DISPLAY_POINTS}" \
    --max-reasonable-gpx-speed-kmh "${MAX_REASONABLE_GPX_SPEED_KMH}" \
    --import-stage pretrip \
    --overwrite
  )
  if [[ -d "${MATERIAL_ROOT}" ]]; then
    IMPORT_ARGS+=(--material-root "${MATERIAL_ROOT}")
  fi
  PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" "${IMPORT_ARGS[@]}"

  echo "Running pretrip layer preparation..."
  PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" -m pretrip_layer_preparation \
    --project-id "${PROJECT_ID}" \
    --workspace-root "${WORKSPACE_ROOT}" \
    --layers "${LAYERS}" \
    --profile pi-offline \
    --network-mode no-network \
    --route-evidence-bundle normalized/routes/route_evidence_bundle.json \
    --route-corridor-m "${ROUTE_CORRIDOR_M}" \
    --reference-track-corridor-m "${REFERENCE_TRACK_CORRIDOR_M}" \
    --ai-mode fixture-or-precomputed \
    --ai-output-policy hash-and-summary

  echo "Running spec alignment verifier..."
  VERIFY_ARGS=(
    tools/verify_pretrip_workspace_spec_alignment.py
    --workspace-root "${WORKSPACE_ROOT}"
    --project-id "${PROJECT_ID}"
    --admin-base-url "${ADMIN_BASE_URL}"
  )
  if [[ -n "${ADMIN_BEARER_TOKEN_FILE}" ]]; then
    VERIFY_ARGS+=(--admin-bearer-token-file "${ADMIN_BEARER_TOKEN_FILE}")
  fi
  PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" "${VERIFY_ARGS[@]}"

  echo "Pretrip workspace rebuild complete."
} | tee "${LOG_PATH}"
