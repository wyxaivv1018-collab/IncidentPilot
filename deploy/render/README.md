# IncidentPilot on Render (free web service)

Free public judge demo URL: `https://<service>.onrender.com/`

## Why Render
Hugging Face Docker Spaces now require PRO. Render free web services do not.

## Create
1. Connect GitHub repo `wyxaivv1018-collab/IncidentPilot` in Render.
2. New → Blueprint (or Web Service from this `render.yaml`), plan **Free**, Docker runtime.
3. Set secret env `NEBIUS_API_KEY` (Token Factory key). Never commit it.
4. Deploy. Cold start after idle can take ~30–60s.

## Runtime
Container uses the root `Dockerfile` and `deploy/hf-space/entrypoint.sh`.
Render injects `RENDER_EXTERNAL_HOSTNAME` / `PORT`; public Host/Origin checks follow that hostname.

## Storage limitation

The service remains on the free plan. Local run history and the usage ledger can be lost on
host restarts, idle shutdown or redeployment. The ledger is a local estimate, not a durable
account-wide cap or a provider-balance check. Download any reports that must be retained.
This repair prevents an already-running server from recreating a lost/corrupt ledger; it
does not add paid disks or solve persistence across replacement service instances.
