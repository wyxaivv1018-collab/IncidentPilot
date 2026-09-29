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
