# IncidentPilot

An evidence-driven incident response agent using NVIDIA Nemotron on Nebius Token Factory.
The model investigates and selects tools. Code enforces permissions, budgets and independent
recovery checks. A successful operation alone never establishes recovery.

## Scope

This release includes project-owned HTTP and background-task test services. It does not
connect to your company's systems. New systems require a connector implementing reads,
allowed operations and business verification. Live, offline test and recorded modes are labelled.

## Run locally

Install Python 3.10+ and uv. From the extracted project directory:

```sh
uv sync --frozen
uv run --frozen --with-requirements docs/nebius/runtime-requirements.txt python scripts/run_nebius.py serve
```

Open http://127.0.0.1:4180/. This starts a free offline test mode using real local services.
For model-led investigation, configure NEBIUS_API_KEY in your external environment and add
`--live` to the serve command. Never place a key in this repository. Starting the server does
not call the model; pressing Investigate in live mode does. The persistent development ceiling
is $0.80. Failed requests retain reservations. Do not remove the ledger to bypass its ceiling.

On Windows, `powershell -NoProfile -File scripts/run_nebius.ps1 -Live` also reads the external
Windows user environment. Services run only while the launcher is running.

## Validate

```sh
uv run --frozen pytest -q tests/unit/test_connected.py tests/api/test_connected_server.py
uv run --frozen ruff check src/incidentpilot/connected tests/unit/test_connected.py tests/api/test_connected_server.py
```

Six CLI real-model cases passed: four recoveries and two permission/evidence handoffs.
Two additional live browser investigations passed on September 29, 2026. See the included
evidence and [validation notes](docs/nebius/VALIDATION.md). These are controlled-service tests,
not proof of production reliability. First-attempt failures and comparison limitations are retained.

## Architecture and origin

See [architecture](docs/nebius/ARCHITECTURE.md), [project origin](docs/nebius/PROVENANCE.md),
[submission description](docs/nebius/SUBMISSION.md) and [provider feedback](docs/nebius/FEEDBACK.md).
This is a substantial competition-period update to an existing project, not a new-project claim.
Source is MIT licensed. The public candidate contains application source and focused release
tests; internal coordination, credentials, developer caches and unrelated runtime are excluded.
The complete internal test suite remains in the development workspace.

Public hosting, free judge access through the judging period and YouTube publication remain
pending account arrangements. Local developer key setup is not the judge-access plan.
No Devpost submission has been made. Final submission is assigned to Grokbot by the owner.
