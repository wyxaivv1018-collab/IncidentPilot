#!/bin/sh
set -eu
# Prefer explicit override, then Render, then Hugging Face SPACE_HOST.
HOSTNAME="${INCIDENTPILOT_PUBLIC_HOSTNAME:-${RENDER_EXTERNAL_HOSTNAME:-${SPACE_HOST:-}}}"
if [ -z "$HOSTNAME" ] && [ -n "${RENDER_EXTERNAL_URL:-}" ]; then
  # e.g. https://incidentpilot.onrender.com -> incidentpilot.onrender.com
  HOSTNAME=$(printf '%s' "$RENDER_EXTERNAL_URL" | sed -e 's|^https://||' -e 's|^http://||' -e 's|/.*||')
fi
if [ -z "$HOSTNAME" ]; then
  echo "INCIDENTPILOT_PUBLIC_HOSTNAME (or RENDER_EXTERNAL_HOSTNAME / SPACE_HOST) is required for public hosting" >&2
  exit 1
fi
export INCIDENTPILOT_PUBLIC_HOST=1
export INCIDENTPILOT_PUBLIC_HOSTNAME="$HOSTNAME"
# NEBIUS_API_KEY must come from host secrets only; never echo it.
PORT="${PORT:-7860}"
exec python scripts/run_nebius.py serve --live --public-host --public-hostname "$HOSTNAME" --port "$PORT"
