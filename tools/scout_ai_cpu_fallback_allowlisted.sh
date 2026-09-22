#!/usr/bin/env bash
set -euo pipefail

# This exact script is allowlisted by PowerSafetySupervisor. It starts a new
# CPU run and never changes hardware power state.
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$repo_root/venv/bin/python" "$repo_root/tools/scout_ai_six_forces_aihat2_eval.py" "$@" \
  --backend ollama_cpu \
  --allow-power-safety-override
