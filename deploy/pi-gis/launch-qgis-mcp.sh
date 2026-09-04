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

display_number="${SCOUT_XVFB_DISPLAY_NUMBER:-99}"
case "${display_number}" in
    ''|*[!0-9]*)
        printf '%s\n' "SCOUT_XVFB_DISPLAY_NUMBER must be numeric" >&2
        exit 2
        ;;
esac

auth_file="${runtime_dir}/Xauthority"
xvfb_log="${state_root}/qgis-mcp/xvfb.log"
display_socket="/tmp/.X11-unix/X${display_number}"
touch "${auth_file}"
chmod 0600 "${auth_file}"
cookie="$(mcookie)"
XAUTHORITY="${auth_file}" xauth add ":${display_number}" . "${cookie}"

Xvfb ":${display_number}" \
    -screen 0 1280x800x24 \
    -nolisten tcp \
    -auth "${auth_file}" \
    >"${xvfb_log}" 2>&1 &
xvfb_pid=$!

attempt=0
while [ "${attempt}" -lt 100 ]; do
    if [ -S "${display_socket}" ]; then
        break
    fi
    if ! kill -0 "${xvfb_pid}" 2>/dev/null; then
        printf '%s\n' "Xvfb exited before the display became ready" >&2
        cat "${xvfb_log}" >&2
        exit 1
    fi
    attempt=$((attempt + 1))
    sleep 0.1
done
if [ ! -S "${display_socket}" ]; then
    printf '%s\n' "Xvfb display did not become ready" >&2
    kill "${xvfb_pid}" 2>/dev/null || true
    exit 1
fi

export DISPLAY=":${display_number}"
export XAUTHORITY="${auth_file}"

exec qgis \
    --profiles-path "${profile_root}" \
    --profile "${profile_name}" \
    --nologo \
    --noversioncheck \
    "$@"
