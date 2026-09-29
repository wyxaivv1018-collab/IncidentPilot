# Nebius / NVIDIA experience feedback — evidence-qualified draft

Chosen integration: NVIDIA `nvidia/nemotron-3-super-120b-a12b` through Nebius Token Factory's
OpenAI-compatible API, wrapped by the existing Strands OpenAIModel.

Observed during implementation:

- Official model cookbooks provide an exact regional endpoint and model identifier. The
  function-calling documentation cleanly separates model intent from application execution.
- The official cost-comparison example includes explicit input/output rates and usage-based
  cost accounting. Those are useful inputs for a small-budget integration.
- The pricing page redirects to the Token Factory console; the public text extraction did
  not expose its current model table. A dated machine-readable price catalog would make
  budget enforcement and reproducible demonstrations easier.
- An isolated fake-SSE test exercised actual Strands tool-call parsing and usage extraction
  without spending promotional credit. It is an integration check, not Nebius service feedback.

Measured on September 28: authenticated catalogue reports tools/reasoning support and rates
$0.30/M input, $0.90/M output. Strands tool-call IDs and token usage were returned in 96 real
requests. Total estimated cost $0.0446079. Final six IncidentPilot investigations took
70.393 seconds total. Four repairable cases recovered; missing permission/evidence handed off.
The model initially skipped useful diagnostic logs on the locked task and handed off too early;
a general investigation prompt correction led to log-based adaptation and verified recovery.
This shows tool-use capability and an observed reliability limitation, not a production guarantee.
The generic agent tied the initial IncidentPilot outcomes; revised results are development-informed.
Account billing reconciliation and exact credit expiry remain unavailable.

Suggested product improvement: expose remaining promotional credit and its exact expiration
through a documented read-only API. An agent's local spending ledger cannot establish the
account's external balance or guarantee judge access months after a trial expires.
