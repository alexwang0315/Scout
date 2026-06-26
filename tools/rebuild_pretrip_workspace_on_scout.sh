#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${SCOUT_PROJECT_ID:-chilai_nanhua_day1}"
WORKSPACE_ROOT="${SCOUT_PRETRIP_WORKSPACE_ROOT:-/data/scout/admin/pretrip-workspaces}"
MATERIAL_ROOT="${SCOUT_PRETRIP_MATERIAL_ROOT:-/data/scout/materials/pretrip/${PROJECT_ID}}"
MATERIAL_MANIFEST="${MATERIAL_ROOT}/material_manifest.json"
MATERIAL_SOURCE_GPX_ROOT=""
MATERIAL_GOLDEN_ROUTE_GPX=""
if [[ -f "${MATERIAL_MANIFEST}" ]]; then
  MATERIAL_VALUES="$(
    python3 - "${MATERIAL_MANIFEST}" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
sources = manifest.get("sources", {})

def source_path(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("path", "")
    return ""

gpx_root = source_path(sources.get("gpx_corpus"))
if not gpx_root:
    reference_gpx = sources.get("reference_gpx")
    if isinstance(reference_gpx, list) and reference_gpx:
        first_path = source_path(reference_gpx[0])
        if first_path:
            gpx_root = str(Path(first_path).parent)

golden = (
    source_path(sources.get("primary_gpx"))
    or source_path(sources.get("golden_route_reference"))
    or source_path(sources.get("golden_route_gpx"))
)
print(gpx_root)
print(golden)
PY
  )"
  MATERIAL_SOURCE_GPX_ROOT="$(printf '%s\n' "${MATERIAL_VALUES}" | sed -n '1p')"
  MATERIAL_GOLDEN_ROUTE_GPX="$(printf '%s\n' "${MATERIAL_VALUES}" | sed -n '2p')"
fi
if [[ -z "${SCOUT_SOURCE_GPX_ROOT:-}" ]]; then
  SOURCE_GPX_ROOT="${MATERIAL_SOURCE_GPX_ROOT:-/data/scout/source-gpx/twmap-gpx-yunhai}"
else
  SOURCE_GPX_ROOT="${SCOUT_SOURCE_GPX_ROOT}"
fi
if [[ -z "${SCOUT_GOLDEN_ROUTE_GPX:-}" ]]; then
  GOLDEN_ROUTE_GPX="${MATERIAL_GOLDEN_ROUTE_GPX:-${SOURCE_GPX_ROOT}/能高安東軍縱走.gpx.gpx}"
else
  GOLDEN_ROUTE_GPX="${SCOUT_GOLDEN_ROUTE_GPX}"
fi
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "./venv/bin/python" ]]; then
    PYTHON_BIN="./venv/bin/python"
  elif [[ -x "./.venv/bin/python" ]]; then
    PYTHON_BIN="./.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi
ADMIN_BASE_URL="${SCOUT_PRETRIP_ADMIN_BASE_URL:-http://127.0.0.1:9100}"
ADMIN_BEARER_TOKEN_FILE="${SCOUT_ADMIN_BEARER_TOKEN_FILE:-}"
CHECKPOINT_SPACING_M="${SCOUT_CHECKPOINT_SPACING_M:-500}"
MAX_REFERENCE_DISPLAY_POINTS="${SCOUT_MAX_REFERENCE_DISPLAY_POINTS:-2500}"
MAX_REASONABLE_GPX_SPEED_KMH="${SCOUT_MAX_REASONABLE_GPX_SPEED_KMH:-120}"
MAX_PREVIOUS_GPX_SPEED_RATIO="${SCOUT_MAX_PREVIOUS_GPX_SPEED_RATIO:-8.0}"
ROUTE_CONTEXT_LIMIT_ROUTE_NOTES="${SCOUT_ROUTE_CONTEXT_LIMIT_ROUTE_NOTES:-80}"
ROUTE_CONTEXT_INCLUDE_ROUTE_NOTES="${SCOUT_ROUTE_CONTEXT_INCLUDE_ROUTE_NOTES:-1}"
ROUTE_CORRIDOR_M="${SCOUT_ROUTE_CORRIDOR_M:-500}"
REFERENCE_TRACK_CORRIDOR_M="${SCOUT_REFERENCE_TRACK_CORRIDOR_M:-300}"
LAYER_PROFILE="${SCOUT_PRETRIP_LAYER_PROFILE:-pi-online-explicit}"
NETWORK_MODE="${SCOUT_PRETRIP_NETWORK_MODE:-explicit-fetch}"
ALLOW_NETWORK_FETCH="${SCOUT_PRETRIP_ALLOW_NETWORK_FETCH:-1}"
DURABLE_EVIDENCE_SOURCE_ROOT="${SCOUT_PRETRIP_DURABLE_EVIDENCE_SOURCE_ROOT:-}"
IMAGERY_SEED_CACHE="${SCOUT_PRETRIP_SEED_IMAGERY_CACHE:-1}"
IMAGERY_PROVIDER_ALLOWS_OFFLINE_PREFETCH="${SCOUT_PRETRIP_IMAGERY_PROVIDER_ALLOWS_OFFLINE_PREFETCH:-1}"
IMAGERY_MIN_ZOOM="${SCOUT_PRETRIP_IMAGERY_MIN_ZOOM:-5}"
IMAGERY_MAX_ZOOM="${SCOUT_PRETRIP_IMAGERY_MAX_ZOOM:-14}"
IMAGERY_SEED_MAX_TILES="${SCOUT_PRETRIP_IMAGERY_SEED_MAX_TILES:-250}"
if [[ -n "${SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT:-}" && -z "${SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT:-}" ]]; then
  export SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT="${SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT}"
fi
BACKUP_ROOT="${SCOUT_PRETRIP_BACKUP_ROOT:-${WORKSPACE_ROOT}}"
LOG_ROOT="${SCOUT_PRETRIP_REBUILD_LOG_ROOT:-/tmp}"
LAYERS="${SCOUT_PRETRIP_LAYERS:-osm,overpass,terrain,risk-score,risk-ribbon,risk-heatmap,risk-delta,cwa-qpf,soil-moisture,antecedent-rain,cwa-weather,imagery,weather,reference-tracks,route,segments,checkpoints,pois,hazards,corridors,retreat,route-notes}"
SCOUT_ENV_FILE="${SCOUT_ENV_FILE:-}"
if [[ -z "${SCOUT_ENV_FILE}" ]]; then
  for candidate in "./.env" "/home/alexwang0315/scout-fusion/.env" "/data/scout/config/.env"; do
    if [[ -f "${candidate}" ]]; then
      SCOUT_ENV_FILE="${candidate}"
      break
    fi
  done
fi
if [[ -n "${SCOUT_ENV_FILE}" && -f "${SCOUT_ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "${SCOUT_ENV_FILE}"
  set +a
  SCOUT_ENV_FILE_LOADED="${SCOUT_ENV_FILE}"
else
  SCOUT_ENV_FILE_LOADED=""
fi

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
  echo "layer_profile=${LAYER_PROFILE}"
  echo "network_mode=${NETWORK_MODE}"
  echo "allow_network_fetch=${ALLOW_NETWORK_FETCH}"
  echo "environment_layer_env_file_loaded=${SCOUT_ENV_FILE_LOADED}"
  echo "route_context_include_route_notes=${ROUTE_CONTEXT_INCLUDE_ROUTE_NOTES}"
  echo "route_context_limit_route_notes=${ROUTE_CONTEXT_LIMIT_ROUTE_NOTES}"
  echo "durable_evidence_source_root=${DURABLE_EVIDENCE_SOURCE_ROOT}"
  echo "raster_tile_cache_root=${SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT:-}"
  echo "imagery_seed_cache=${IMAGERY_SEED_CACHE}"
  echo "imagery_zoom_range=${IMAGERY_MIN_ZOOM}-${IMAGERY_MAX_ZOOM}"
  echo "imagery_seed_max_tiles=${IMAGERY_SEED_MAX_TILES}"
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
    --max-previous-gpx-speed-ratio "${MAX_PREVIOUS_GPX_SPEED_RATIO}" \
    --import-stage pretrip \
    --overwrite
  )
  if [[ -d "${MATERIAL_ROOT}" ]]; then
    IMPORT_ARGS+=(--material-root "${MATERIAL_ROOT}")
  fi
  PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" "${IMPORT_ARGS[@]}"

  RESTORE_SOURCE_ROOT=""
  if [[ -n "${DURABLE_EVIDENCE_SOURCE_ROOT}" && -f "${DURABLE_EVIDENCE_SOURCE_ROOT}/project.json" ]]; then
    RESTORE_SOURCE_ROOT="${DURABLE_EVIDENCE_SOURCE_ROOT}"
  elif [[ -f "${BACKUP_PATH}/project.json" ]]; then
    RESTORE_SOURCE_ROOT="${BACKUP_PATH}"
  fi
  if [[ -n "${RESTORE_SOURCE_ROOT}" ]]; then
    echo "Restoring durable admin evidence refs from ${RESTORE_SOURCE_ROOT}..."
    PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" - "${PROJECT_ROOT}" "${RESTORE_SOURCE_ROOT}" <<'PY'
import json
import sys
from pathlib import Path

from pretrip_import import restore_durable_admin_evidence_refs

summary = restore_durable_admin_evidence_refs(
    project_root=Path(sys.argv[1]),
    source_root=Path(sys.argv[2]),
)
print(json.dumps({"durable_admin_evidence_restore": summary}, ensure_ascii=False, sort_keys=True))
PY
  else
    echo "No prior or explicit durable admin evidence source found."
  fi

  echo "Building reference segment timing evidence..."
  PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" \
    -m pretrip_reference_segment_timing \
    --project-root "${PROJECT_ROOT}" \
    --project-id "${PROJECT_ID}"

  echo "Running pretrip layer preparation..."
  LAYER_ARGS=(
    -m pretrip_layer_preparation
    --project-id "${PROJECT_ID}"
    --workspace-root "${WORKSPACE_ROOT}"
    --layers "${LAYERS}"
    --profile "${LAYER_PROFILE}"
    --network-mode "${NETWORK_MODE}"
    --route-evidence-bundle normalized/routes/route_evidence_bundle.json
    --route-corridor-m "${ROUTE_CORRIDOR_M}"
    --reference-track-corridor-m "${REFERENCE_TRACK_CORRIDOR_M}"
    --ai-mode fixture-or-precomputed
    --ai-output-policy hash-and-summary
  )
  if [[ "${ALLOW_NETWORK_FETCH}" == "1" || "${ALLOW_NETWORK_FETCH}" == "true" || "${ALLOW_NETWORK_FETCH}" == "TRUE" ]]; then
    LAYER_ARGS+=(--allow-network-fetch)
  fi
  if [[ "${IMAGERY_SEED_CACHE}" == "1" || "${IMAGERY_SEED_CACHE}" == "true" || "${IMAGERY_SEED_CACHE}" == "TRUE" ]]; then
    LAYER_ARGS+=(--seed-imagery-cache)
    if [[ "${IMAGERY_PROVIDER_ALLOWS_OFFLINE_PREFETCH}" == "1" || "${IMAGERY_PROVIDER_ALLOWS_OFFLINE_PREFETCH}" == "true" || "${IMAGERY_PROVIDER_ALLOWS_OFFLINE_PREFETCH}" == "TRUE" ]]; then
      LAYER_ARGS+=(--imagery-provider-allows-offline-prefetch)
    fi
    LAYER_ARGS+=(
      --imagery-min-zoom "${IMAGERY_MIN_ZOOM}"
      --imagery-max-zoom "${IMAGERY_MAX_ZOOM}"
      --imagery-seed-max-tiles "${IMAGERY_SEED_MAX_TILES}"
    )
  fi
  PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" "${LAYER_ARGS[@]}"

  echo "Collecting Sec. 6 route context evidence..."
  ROUTE_CONTEXT_ARGS=(
    -m pretrip_route_context_collection
    --project-root "${PROJECT_ROOT}"
    --limit-route-notes "${ROUTE_CONTEXT_LIMIT_ROUTE_NOTES}"
  )
  if [[ "${ROUTE_CONTEXT_INCLUDE_ROUTE_NOTES}" == "0" || "${ROUTE_CONTEXT_INCLUDE_ROUTE_NOTES}" == "false" || "${ROUTE_CONTEXT_INCLUDE_ROUTE_NOTES}" == "FALSE" ]]; then
    ROUTE_CONTEXT_ARGS+=(--no-route-notes)
  fi
  PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" "${ROUTE_CONTEXT_ARGS[@]}"

  if [[ -n "${DURABLE_EVIDENCE_SOURCE_ROOT}" && -f "${DURABLE_EVIDENCE_SOURCE_ROOT}/project.json" ]]; then
    echo "Finalizing durable admin evidence refs from ${DURABLE_EVIDENCE_SOURCE_ROOT}..."
    PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" - "${PROJECT_ROOT}" "${DURABLE_EVIDENCE_SOURCE_ROOT}" <<'PY'
import json
import sys
from pathlib import Path

from pretrip_import import restore_durable_admin_evidence_refs

summary = restore_durable_admin_evidence_refs(
    project_root=Path(sys.argv[1]),
    source_root=Path(sys.argv[2]),
    overwrite_existing=True,
)
print(json.dumps({"durable_admin_evidence_final_restore": summary}, ensure_ascii=False, sort_keys=True))
PY
  fi

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
  if [[ "${ALLOW_NETWORK_FETCH}" == "1" || "${ALLOW_NETWORK_FETCH}" == "true" || "${ALLOW_NETWORK_FETCH}" == "TRUE" ]]; then
    VERIFY_ARGS+=(--allow-network-calls)
  fi
  PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" "${VERIFY_ARGS[@]}"

  echo "Pretrip workspace rebuild complete."
} | tee "${LOG_PATH}"
