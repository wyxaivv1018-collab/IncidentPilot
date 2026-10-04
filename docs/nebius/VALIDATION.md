# Validation and comparison — current evidence

Workspace: `D:\CodexProjects\IncidentPilot`.

## Offline evidence obtained

- Complete-worktree baseline: 529 archived files, ZIP readback hashes all match.
- Historical C11 accepted evidence: 23/23 frozen file hashes match. Its PASS/CLOSED is preserved.
- New connector/guard/budget tests: 12 passed. Real local HTTP requests and real queued task
  execution/artifact validation are included. These are not live-model tests.
- Actual Strands 1.36.0/OpenAI adapter with a fake SSE transport: PASS, three mock model responses,
  provider tool-call binding and usage accounting exercised. Paid API requests: zero.
- Full Python suite: 296 passed on the final code checkpoint (15.67 seconds).
- Ruff: PASS. Existing tracked-file secret check: PASS. UI build: PASS.
- UI suite: 21 passed. The transport-confinement contract now explicitly admits the new v2
  API module and still rejects transport elsewhere or arbitrary execution endpoints.
- Actual Chrome: six offline workflows passed, same-run reports rendered, history marked RECORDED,
  English/Chinese label switching, desktop and 430px layout, no horizontal overflow or JS errors.
  Evidence: `runtime/nebius/browser/check.json` and screenshots.

## Measured fixed-SOP baseline

Same synthetic user descriptions, connector information and action permissions as the planned
model arms. The disclosed SOP reads status/logs, restarts the HTTP listener or retries the task,
then checks recovery. It does not adapt to a changed cause.

| Case | Result | Executed action | Seconds | Required handoff | Model cost |
| --- | --- | --- | ---: | ---: | ---: |
| HTTP listener stopped | Recovered | restart_service | 2.076 | 0 | $0 |
| HTTP dependency disconnected | Not recovered | restart_service | 0.051 | 1 | $0 |
| Background transient failure | Recovered | retry_task | 0.009 | 0 | $0 |
| Background orphaned lock | Not recovered | retry_task | 0.006 | 1 | $0 |
| Missing mutation permission | Human handoff, no mutation | none | 4.038 | 1 | $0 |
| Missing monitoring evidence | Human handoff, no mutation | none | 0.005 | 1 | $0 |

Source: `runtime/nebius/comparison-offline.json`. These are one repetition per case, sequential,
not randomized. Handoff count is a programmatic requirement, not observed human labor/time.
Fast in-process worker timings cannot be generalized to production outages.

## Live validation update — 2026-09-28

External NEBIUS_API_KEY is readable; authenticated catalogue preflight passed. Real NVIDIA
Nemotron inference and provider-originated tools ran through Nebius Token Factory. No fallback.
Final six-case acceptance: **PASS**, `runtime/nebius/acceptance.json`. Four repairable cases
recovered; missing permission/evidence produced handoff with no mutations. Actual HTTP content
and current-job result artifacts were verified independently. Original failed locked-task runs
remain preserved; they were not relabelled as successes.

Initial generic and IncidentPilot arms each recovered 3/4 repairable cases, with 2/2 correct
access-related handoffs. Both handed off prematurely on the locked job. The IncidentPilot prompt
was revised to investigate available diagnostics and avoid guessing from failure status.
The revised model read lock logs, selected unlock then retry, and recovered. It still tried an
initial retry before logs: the current result proves adaptation, not perfect first-action diagnosis.
All six IncidentPilot cases were checked under the revised prompt; unchanged generic/SOP results
were reused. This is a development-informed sample, not a blind or statistically significant win.

| Method | Recovered / repairable | Correct access handoffs | Total seconds, 6 cases | Estimated model cost |
| --- | ---: | ---: | ---: | ---: |
| Fixed SOP | 2/4 | 2/2 | 6.185 | $0 |
| Same-model generic | 3/4 | 2/2 | 101.999 | $0.0159132 |
| IncidentPilot revised | 4/4 | 2/2 | 70.393 | $0.0147255 |

Time includes model/tool execution, not human repair time. Human-step counts are required
handoffs (4, 3, 2 respectively), not measured human labour. One sequential repetition, no
randomization. First-attempt comparison is preserved in
`runtime/nebius/live-validation-20260928/comparison-first-attempt.json`.

Cumulative ledger: **96 real model requests, $0.0446079 estimated**, $0 unresolved usage
reservation. Remaining local development allowance: **$0.7553921** under $0.80 ceiling;
remaining of the user-reported $1 before other charges: **$0.9553921**, not account-confirmed.
Usage-based estimates are not a reconciled invoice. Exact credit balance/expiry and judge-period
funding remain unverified. No top-up, payment binding or paid infrastructure was created.

Current live page: http://127.0.0.1:4180/ ; launcher: `scripts/run_nebius.ps1 -Live`.
Opening the page or recorded reports costs nothing; starting a live investigation consumes the
same persistent budget. This is a local running process, not a public or reboot-persistent site.

Checks after fixes: 15 focused Python tests PASS; Ruff PASS. The previous 296 full Python,
21 UI and six offline-browser results remain dated offline evidence, not new real-model evidence.
Budget per-run reports now show globally remaining allowance; enforcement was already global.
History ordering now uses report time rather than random run IDs. Old reports remain immutable.
Real-run comparison and implementation hashes: `runtime/nebius/live-validation-20260928/`.

Development and local real-model validation are complete for these owned test cases.
Public release and competition submission are **NOT COMPLETE**. Reviewable source, English
materials and video are local only. Required owner decisions: public repository destination and
publish permission, free judge access through December 15, YouTube publication, entrant/account
and final Devpost authorization. No remote repository/push/upload/submission has occurred.

## Final local artifact checks — 2026-09-28

- Six real-report browser views PASS, no JavaScript exceptions or mobile overflow;
  `runtime/nebius/browser-live-review/check.json`. These checks read saved live reports,
  do not run new inference, and are not a claim of a newly executed live browser workflow.
- English-captioned real-report video: 67.5 seconds, 1,232,162 bytes, full MP4 decode PASS.
  `runtime/nebius/video-live-review/IncidentPilot-real-evidence-demo.mp4`.
  Always labelled RECORDED; no new model call during capture. Public YouTube URL absent.
- Server tests after chronological-history change: 2 passed in 1.35 seconds.
- Current tested model implementation hashes: live-validation-20260928/final-implementation.json.
- Remaining technical scope limitation: live model/service E2E ran through the CLI; browser
  controls were exercised offline and real report rendering was checked separately.
- Source bundle: runtime/nebius/release/IncidentPilot-Nebius-source.zip.
- New evidence bundle: runtime/nebius/release/IncidentPilot-real-evidence.zip.
- Final bundle integrity/secret-scan records: source-manifest.json and real-evidence-manifest.json.
  These local deliverables do not establish public access or a competition submission.

## September 29 — live browser completion

The actual browser selected live mode and clicked Investigate for HTTP stopped and locked
background-task cases. Both recovered; provider tool provenance, actual business verification,
same-run cards, history labels and mobile layout passed. No JavaScript exceptions.
Run IDs: RUN-NEBIUS-b5b63ceed79a and RUN-NEBIUS-b21c1d52882f.
Evidence: runtime/nebius/browser-live/check.json. The earlier CLI-only limitation is now closed
for these two browser workflows, not for arbitrary external system integrations.

New video: runtime/nebius/video-live/IncidentPilot-live-browser-demo.mp4, 63 seconds,
English captions, actual live browser operation followed by explicitly labelled history.
Full decode PASS. Prior offline and recorded-review videos remain separate.

Cumulative ledger at browser completion: 113 requests, $0.0533151 estimated, no unresolved
usage reservations. Remaining development allowance $0.7466849; account balance/expiry
remain unverified. Browser pair cost $0.0069171 (13 requests). The ledger contained 100
requests before this pair, versus the previous recorded 96; all costs remain included.

User authorized public repository wyxaivv1018-collab/IncidentPilot and YouTube channel
@yxw-y1v. Final Devpost submission belongs to Grokbot. No hosting account was provided.
Repository/video publication and free judge access require separately verified completion.

## 2026-10-05 defect repair validation

This revision repairs existing behavior only:

- Resume status polling after an uncertain POST response; lock inputs during active runs.
- Display the server's execution mode on refresh and reconnect.
- Preserve interrupted offline/SOP reports and accept cancellation during session startup.
- Ignore an old run's delayed cancellation response after another run has started.
- Resolve Windows-only dependencies conditionally for Linux deployment.
- Reuse the server's budget ledger for every run and reject lost/corrupt storage within the
  running process instead of silently recreating an allowance.

The owner declined new hosting charges. The free Render configuration is retained. Durable
history and cumulative accounting across host replacements remain unresolved: free hosting
can discard both. No paid infrastructure or new incident capability is introduced.

Final free-hosting-compatible regression checks: 35 Python tests and 9 Node UI tests passed.
`ruff check .`, `git diff --check`, and the inherited tracked-file credential scan passed.
The Docker requirements entry also resolves on Linux x86_64 / Python 3.11. No paid model
call was made for this repair. Deployment and submission are verified separately below.
