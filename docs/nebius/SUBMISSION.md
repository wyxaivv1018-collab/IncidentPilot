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

## Published links and submission status

- Public source repository: https://github.com/wyxaivv1018-collab/IncidentPilot
- Free working demo/test-build URL valid through judging: https://incidentpilot-judge.onrender.com/
- Public YouTube demo under three minutes: https://youtu.be/SFowqxkH0Gg
- Devpost status: **SUBMITTED** to **Nebius x NVIDIA Global AI Hackathon** (user-confirmed 2026-09-30 ~14:21 Asia/Shanghai)
- Devpost submission id: **1174683**
- Owner: **v pyw / @wyxaivv1018-collab**
- Evidence: the project page shows **SUBMITTED TO Nebius x NVIDIA Global AI Hackathon** with **Edit hackathon submission**; the YouTube embed is present.

No confirmation email id is recorded.


## October 5, 2026 reliability revision

The existing submission **1174683** was updated and saved, with no new project created.
Code revision **e16249b** is published on the same repository's `main` branch and deployed
on the same free demo URL. The public project page is:
https://devpost.com/software/incidentpilot-oty2b3

Devpost finalization was read back as **SUBMITTED**, **5/5 steps done**, **Project submitted!**.
The project story and judge-facing update identify the revision and validation results.
The public page separately confirms the update is visible. Tests and deployment evidence are
recorded in VALIDATION.md. No paid infrastructure or paid model calls were added by this repair.
Free-host history and local accounting can still reset on host replacement; this limitation
is disclosed rather than claimed as fixed.
