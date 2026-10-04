# IncidentPilot on Render

Free public judge demo URL: `https://<service>.onrender.com/`

## Persistent runtime required
The original free-instance deployment cannot preserve cumulative spending or reports.
Public live mode now requires a persistent disk and an initialized budget ledger.
Follow [persistent storage setup](PERSISTENT-STORAGE.md) before deploying this revision.
Any paid instance or disk change requires the owner's approval.

## Create
1. Connect GitHub repo `wyxaivv1018-collab/IncidentPilot` in Render.
2. New → Web Service, Docker runtime. The historical free `render.yaml` is not suitable for public live mode. Choose a disk-capable instance only after cost approval.
3. Set secret env `NEBIUS_API_KEY` (Token Factory key). Never commit it.
4. Configure and initialize the persistent store, then deploy and verify preservation across restart.

## Runtime
Container uses the root `Dockerfile` and `deploy/hf-space/entrypoint.sh`.
Render injects `RENDER_EXTERNAL_HOSTNAME` / `PORT`; public Host/Origin checks follow that hostname.
