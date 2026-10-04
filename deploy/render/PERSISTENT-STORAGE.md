# Preserve the existing budget and reports

IncidentPilot stores its cumulative budget, run evidence and reports together. Render free
instances discard local files on restart or idle shutdown. Public live mode therefore refuses
to start without an explicitly configured mounted data directory and a valid budget ledger.

## Existing service migration

1. Preserve any existing budget/evidence before replacing a deployment. A zero request count
   after an ephemeral restart does not prove the account has never spent money. Reconcile the
   remaining model allowance with the owner; do not silently issue a new allowance.
2. Obtain owner approval for paid infrastructure. Attach a persistent disk at `/var/data` to a
   disk-capable instance. The original free `render.yaml` must not be used for public live mode.
3. Set `INCIDENTPILOT_DATA_DIR=/var/data`. Keep the API key in the existing host secret. Before
   deploying the patched image for the first time, temporarily override its Docker command:

   ```sh
   sh -c 'mkdir -p /tmp/incidentpilot-maintenance && printf "Preparing persistent storage.\n" > /tmp/incidentpilot-maintenance/index.html && exec python -m http.server "$PORT" --bind 0.0.0.0 --directory /tmp/incidentpilot-maintenance'
   ```

   Deploy the patched image with this temporary command. It serves only a maintenance page;
   it does not load the model key or create a budget. This makes the new initialization script
   available in the service shell without attempting normal startup against an empty disk.
4. Restore the preserved ledger and run evidence to `/var/data`. For a genuinely new empty
   disk with no ledger to restore, first confirm the remaining allowance explicitly, then run
   this command once from the running service shell:

   ```sh
   python scripts/init_nebius_storage.py --data-dir /var/data --ceiling-usd CONFIRMED_ALLOWANCE
   ```

   The allowance must be positive and at most $0.80. The initializer refuses an existing or
   previously initialized directory. Do not put it in the Docker startup command. A missing
   ledger on a previously initialized disk must be restored rather than initialized again.
5. Remove the temporary Docker command override, restoring the image's normal command
   `./deploy/hf-space/entrypoint.sh`, then redeploy. A missing, invalid or unmounted store
   must stop startup. Never delete a ledger or initialization marker to get startup to pass.
6. Verify the same remaining allowance and saved reports before and after a service restart.
   Initialization alone does not establish that the deployment persistence check passed.

Owned test services and run reports use this same selected runtime root. The local developer
path remains `runtime/nebius`; this revision adds no incident capabilities or provider changes.
