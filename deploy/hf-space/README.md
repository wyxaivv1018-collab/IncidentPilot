# IncidentPilot judge demo on Hugging Face Spaces

Free public hosting for the Nebius Token Factory hackathon judge demo.
This pack runs the existing connected UI/API with **public Host/Origin checks**
so Spaces can reverse-proxy HTTPS to the app.

## What judges get

- UI at `https://<your-space>.hf.space/`
- Offline-test mode works without a key
- Live mode uses **Space secret** `NEBIUS_API_KEY` only (never commit a key)
- Same $0.80 development budget ledger as local runs

## Create the Space

1. Create a **Docker** Space (SDK: Docker), public or gated for judges.
2. Point it at this repository (or copy `deploy/hf-space/Dockerfile` to the Space root
   and keep the IncidentPilot source tree available at build context root).
3. In Space **Settings → Secrets**, add:
   - `NEBIUS_API_KEY` — Token Factory key for live Investigate only
4. Optional Space variables:
   - `INCIDENTPILOT_PUBLIC_HOSTNAME` — e.g. `username-incidentpilot.hf.space`
     (defaults to Hugging Face `SPACE_HOST` when unset)
   - `INCIDENTPILOT_PUBLIC_HOST=1` — already set in the Dockerfile
   - `PORT` — defaults to `7860` (Spaces standard)

Do **not** put API keys in the Dockerfile, README, git history, or Space variables
that are marked public.

## How it runs

The container:

1. Installs Linux runtime deps from `deploy/hf-space/requirements.txt` (**no pywin32**).
2. Installs IncidentPilot from the repo root (`pip install -e .`).
3. Starts:

```sh
python scripts/run_nebius.py serve --live --public-host --port "${PORT:-7860}"
```

Public mode binds `0.0.0.0` and trusts only the configured hostname for `Host`
and `https://` / `http://` `Origin` (see `src/incidentpilot/connected/server.py`).
Default local behaviour remains loopback-only when public flags/env are unset.

## Local smoke (no Spaces account required)

```sh
export INCIDENTPILOT_PUBLIC_HOST=1
export INCIDENTPILOT_PUBLIC_HOSTNAME=localhost
# optional: export NEBIUS_API_KEY=...   # never print or commit
uv run --frozen --with-requirements deploy/hf-space/requirements.txt \
  python scripts/run_nebius.py serve --live --public-host --public-hostname localhost --port 7860
```

Then open `http://localhost:7860/` (Host must be `localhost` or `localhost:<port>`).

## Security notes

- Public mode is for **judge demo**, not a multi-tenant SaaS.
- Host/Origin allowlisting still rejects `attacker.invalid`.
- Live calls remain gated by `--live` / `allow_live` and key presence.
- Budget ledger under `runtime/nebius/budget.sqlite` still enforces the ceiling.
- Do not rerun paid Nebius acceptance suites from Spaces just to “check”; use offline-test first.

## Files in this directory

| File | Role |
|------|------|
| `Dockerfile` | Spaces Docker entry |
| `requirements.txt` | Strands/OpenAI stack without Windows `pywin32` |
| `README.md` | This guide |
| `entrypoint.sh` | Resolves hostname from `SPACE_HOST` / secrets-safe env |

