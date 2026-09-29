# IncidentPilot — Evidence to recovery

Track: **Best Apps and Agents**

## Elevator pitch

An incident-response agent that investigates connected applications, chooses permitted repairs,
checks whether the business result actually recovered, and explains what happened in plain language.

## The problem

Small software teams and application-support operators often move between service status,
logs, repair commands and incident notes. A restart can succeed while the user-facing feature
remains broken. A familiar symptom can also have a different cause. The useful outcome is a
verified recovery—or an honest handoff with evidence—rather than a confident command transcript.

## What it does

Select an application, describe the symptom and start an investigation. IncidentPilot reads
current evidence, selects bounded tools, checks permission outside the model, and verifies
the actual service outcome after action. Four cards explain what broke, what was done, whether
it recovered and what the user must do. Expand the evidence for technical detail and download
the same-run report. Missing access or key evidence produces a human handoff.

The test build includes a real HTTP application and a real queued background worker owned
by the project. They require no company infrastructure. A connector interface keeps the core
independent of a specific ERP, CRM or service type.

## How it is built

Python, Strands Agents, the existing IncidentPilot ExecutionGuard, a small connector contract,
standard-library local services, and a dependency-free browser interface. The competition
provider is NVIDIA `nvidia/nemotron-3-super-120b-a12b` on Nebius Token Factory. The model is
responsible for interpreting information, selecting tools and adapting decisions; the program
enforces budget, scope, permissions and actual recovery checks. There is no provider fallback.

## What we tested

Consult `VALIDATION.md` for actual current results and run IDs. Offline service tests, isolated
SDK tests, real-model runs and browser checks are reported separately. A six-case comparison
uses a fixed SOP, the same model in a generic agent, and IncidentPilot. It measures outcomes,
handoff requirements, elapsed time and estimated usage without assuming IncidentPilot wins.

## Origin and limitations

This is a significant competition-period update to an existing project, not a new-from-scratch
claim. See `PROVENANCE.md`. The current connectors cover owned test services, not enterprise
production systems. Small evaluation results are not evidence of production reliability or
measured labor savings. A local working build is distinct from a public judge-ready release.

## Links to fill only after actual publication

- Public source repository: https://github.com/wyxaivv1018-collab/IncidentPilot
- Free working demo/test-build URL valid through judging: **NOT PUBLISHED**
- Public YouTube demo under three minutes: **NOT PUBLISHED**
- Devpost submission confirmation: **NOT SUBMITTED**

Never replace these with an implied completion claim before obtaining the actual URLs/receipt.
