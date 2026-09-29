# PROJECT_STATE

## 2026-09-29 — box-side PUBLIC_HOST for HF Spaces judge demo

- Work done on **Grok Bot box** under `/workspace/IncidentPilot` only (not the Windows machine).
- Added optional public hosting: `INCIDENTPILOT_PUBLIC_HOST=1` + `INCIDENTPILOT_PUBLIC_HOSTNAME`
  (or `--public-host` / `--public-hostname`). Default remains loopback-only.
- Deploy pack: `deploy/hf-space/` (Dockerfile, Linux requirements without pywin32, README).
- Credits / Devpost form submission is being handled from the **box browser separately**;
  this note does not include or trigger any Devpost submit.
- Do not commit API keys; do not rerun paid Nebius acceptance from this change set.

