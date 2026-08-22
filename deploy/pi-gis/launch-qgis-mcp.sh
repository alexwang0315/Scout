#!/bin/sh
set -eu

state_root="${SCOUT_QGIS_STATE_ROOT:-/state}"
profile_name="${SCOUT_QGIS_PROFILE:-scout}"
profile_root="${state_root}"
profile_dir="${profile_root}/profiles/${profile_name}"
runtime_dir="${state_root}/runtime"
home_dir="${state_root}/home"
cache_dir="${state_root}/cache"
connection_file="${QGIS_MCP_CONNECTION_FILE:-${state_root}/qgis-mcp/connection.json}"

mkdir -p \
    "${profile_dir}/QGIS" \
    "${runtime_dir}" \
    "${home_dir}" \
    "${cache_dir}" \
    "$(dirname "${connection_file}")"

if [ ! -f "${profile_dir}/QGIS/QGIS3.ini" ]; then
    cp /opt/scout-qgis/profile/QGIS/QGIS3.ini "${profile_dir}/QGIS/QGIS3.ini"
fi

chmod 0700 \
    "${runtime_dir}" \
    "${home_dir}" \
    "${cache_dir}" \
    "$(dirname "${connection_file}")"

export HOME="${home_dir}"
export XDG_CACHE_HOME="${cache_dir}"
export XDG_RUNTIME_DIR="${runtime_dir}"
export QT_QPA_PLATFORM="${SCOUT_QT_QPA_PLATFORM:-xcb}"
export QGIS_MCP_CONNECTION_FILE="${connection_file}"

exec xvfb-run \
    --auto-servernum \
    --server-args="-screen 0 1280x800x24 -nolisten tcp" \
    qgis \
        --profiles-path "${profile_root}" \
        --profile "${profile_name}" \
        --nologo \
        --noversioncheck \
        "$@"
