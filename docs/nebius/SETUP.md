# Run and reproduce

Use the complete working tree or reviewed release ZIP, not the old Git HEAD.
Python 3.10+ (validated environment: 3.13.13), uv, Node 20+ and Chrome/Edge are required for all
checks. The UI and local test services have no extra framework dependencies.

Windows:

```powershell
Set-Location 'D:\CodexProjects\IncidentPilot'
uv sync --frozen
powershell -NoProfile -File scripts/run_nebius.ps1
```

Browse http://127.0.0.1:4180/. Offline mode executes a disclosed fixed SOP against real owned
services; it is not AI acceptance. Ctrl+C stops the server. No company server is required.

For live mode, set `NEBIUS_API_KEY` in the Windows **User environment variables** dialog
outside this project. The launcher reads it without printing it. Never paste a credential
into a source file, a project `.env`, a screenshot or a report. Launch:

```powershell
powershell -NoProfile -File scripts/run_nebius.ps1 -Live
```

Other platforms (environment variable already supplied externally):

```sh
uv run --frozen --with-requirements docs/nebius/runtime-requirements.txt python scripts/run_nebius.py serve --live
```

The provider is fixed to Nebius/Nemotron, with no fallback. SDK HTTP retries and agent retries
are disabled. Maximum 12 model requests, 24 tools, 240 seconds per run, 35 seconds per request,
4096 output tokens and a conservative 64000 input-token bound per request. The serialized
request includes history and tool definitions. Persistent reservations are committed before
network access and retained when usage is unavailable. Prices are estimates, not invoice proof.

`runtime/nebius/budget.sqlite` is the single development ledger. Its $0.80 ceiling cannot be
silently raised by relaunching. Keep this ledger across restarts. The remaining $0.20 of the
user's $1 authorization is reserved, not automatically enabled. Concurrent unrelated account
spend cannot be observed by this local ledger; account balance must be checked before live work.

Offline checks for the public release (no model charges):

```sh
uv run --frozen pytest -q tests/unit/test_connected.py tests/api/test_connected_server.py
uv run --frozen ruff check src/incidentpilot/connected tests/unit/test_connected.py tests/api/test_connected_server.py
uv run --frozen --with-requirements docs/nebius/runtime-requirements.txt python scripts/nebius_sdk_check.py
uv run --frozen python scripts/run_nebius.py compare
# With the local server running:
node scripts/nebius_browser_check.mjs
```

The complete development workspace additionally runs the full Python suite, tracked-file
credential check and legacy npm UI tests/build. Internal coordination and these historical
workspace-dependent tests are excluded from the public candidate. No development check was
removed or weakened; the release includes its focused connector/API tests and browser tools.

Paid commands, only within the existing authorized balance:

```sh
uv run --frozen python scripts/nebius_preflight.py
uv run --frozen --with-requirements docs/nebius/runtime-requirements.txt python scripts/run_nebius.py run --live --case http-stopped
uv run --frozen --with-requirements docs/nebius/runtime-requirements.txt python scripts/run_nebius.py compare --live
uv run --frozen python scripts/nebius_acceptance.py
```

Each run owns fresh services. HTTP recovery checks a real GET and response content. Background
recovery reads the worker's current-job artifact and independently checks its input hash and sum.
Services are closed at run end; a report proves recovery at its recorded time, not continued hosting.

Evidence is under `runtime/nebius/runs/<run_id>/`; reports can be downloaded from the UI.
SDK mock evidence is kept separately under `runtime/nebius/sdk-offline/` and is never live proof.
Historical C11 and earlier v1 artifacts remain in their original locations. The old UI is
available at `/index.html?mode=recorded`; new report history is explicitly marked RECORDED.

The project has been submitted; current published links are in SUBMISSION.md.
Public live hosting requires INCIDENTPILOT_DATA_DIR to name a persistent mounted directory
with an explicitly initialized budget ledger. See ../../deploy/render/PERSISTENT-STORAGE.md.
Local setup remains optional and does not replace the published judge-access service.
