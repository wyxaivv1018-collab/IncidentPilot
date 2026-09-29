# Origin and competition-period updates

IncidentPilot is an existing project. Its earliest preserved Git commit is
`b242bfa` (2026-08-26 17:38:18 +08:00, 09:38:18 UTC), titled "Establish project baseline".
That timestamp precedes this event's 2026-08-26 09:00 Pacific opening (16:00 UTC).
Earlier coordination records show project work on the same date. The exact first idea/creation
instant cannot be established from Git alone; the preserved commit is an upper bound on origin,
not a claim that work began at that instant. No previous submission is asserted.

The old project investigated a synthetic order-sync scenario using Strands, a safety boundary,
model tool-call provenance, authoritative verification and same-run reporting. The accepted
C11 final record is PASS/CLOSED, with frozen run `RUN-C08-aaad4584d889`. Earlier failed tasks and
the unrecoverable original trigger remain historical failures/limitations.

Before this revision, the complete working tree—not merely HEAD—was saved to
`runtime/nebius/baseline/worktree.zip` and hashed in `manifest.json`: 529 files, including
uncommitted product code and prior runtime evidence. All archive entries were re-read and
validated. The 23 accepted C11 evidence entries were rehashed with zero mismatches.
Reproducible dependencies/caches and Git internals were excluded from the content archive;
HEAD and full working-tree status were recorded separately. No reset or clean was performed.

Substantial work initiated 2026-09-23 during this competition's submission period:

- Nebius-only Strands provider with selected NVIDIA Nemotron, explicit call limits and durable
  conservative cost reservations, replacing provider assumptions for this new entrypoint.
- Connector contract separating system reads, allowed actions and recovery checks from the
  order-sync simulator, while preserving legacy code/evidence readers.
- Real owned HTTP and background services; actual operation effects and business verification.
- Complete system-selection, symptom, investigation, verification/report/handoff UI, reusing
  the established visual system, with distinct live/offline/recorded labels.
- Same-case fixed-SOP/generic-agent/IncidentPilot evaluation harness and evidence exports.
- New offline, API, browser and SDK-adapter checks plus English submission/reproduction material.

The delivery handoff and generated source/baseline difference inventory are the completion
record. This file describes implementation scope; it does not imply that all live, publication
or submission gates have passed. Original frozen acceptance is not acceptance of these updates.

The remote repository separately preserves its four September 9 documentation commits. The competition source import preserves this history; the earlier August 26 origin is from the independently preserved local development repository.
