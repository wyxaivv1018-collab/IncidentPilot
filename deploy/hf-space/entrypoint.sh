#!/bin/sh
set -eu
# Hugging Face injects SPACE_HOST (e.g. user-name.hf.space). Prefer explicit override.
HOSTNAME="${INCIDENTPILOT_PUBLIC_HOSTNAME:-${SPACE_HOST:-}}"
if [ -z "$HOSTNAME" ]; then
  echo "INCIDENTPILOT_PUBLIC_HOSTNAME or SPACE_HOST is required for public Spaces hosting" >&2
  exit 1
fi
export INCIDENTPILOT_PUBLIC_HOST=1
export INCIDENTPILOT_PUBLIC_HOSTNAME="$HOSTNAME"
# NEBIUS_API_KEY must come from Space Secrets only; never echo it.
PORT="${PORT:-7860}"
exec python scripts/run_nebius.py serve --live --public-host --public-hostname "$HOSTNAME" --port "$PORT"
