"""IncidentPilot official synthetic-demo-sop, never an external enterprise SOP.

Sources: coordination/MVP_SCOPE.md (scenario and safety boundary),
coordination/BEHAVIORAL_REPLANNING_CONTRACT.md, and the accepted C03/C04
contracts in simulator/fixtures.py and safety/catalog.py.
These independent conditional suggestions do not prescribe a tool sequence.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DemoSop:
    sop_id: str
    source_kind: str
    scenario_id: str
    title: str
    tokens: tuple[str, ...]
    guidance: str
    references: tuple[str, ...]


SOPS = (
    DemoSop(
        sop_id="synthetic-demo-sop/order-sync-double-fault/v1",
        source_kind="synthetic-demo-sop",
        scenario_id="order-sync-double-fault",
        title="IncidentPilot synthetic order-sync recovery guidance",
        tokens=("order-sync", "sync-worker", "sync_timeout", "cache_lock", "cache",
                "worker", "order", "sync", "failed"),
        guidance=(
            "Synthetic demo knowledge only; not evidence of the current incident. "
            "If current observations establish a stopped sync-worker, the guarded restart "
            "may be considered for that non-critical worker, at most once per run. "
            "If current observations establish an order-sync cache lock, a guarded clear "
            "may be considered only for that namespace and at most 100 synthetic keys. "
            "A retry is limited to the incident's order-sync-job-001, at most twice. "
            "Choose actions from actual observations; adapt the evidence-linked plan when "
            "material new evidence invalidates it. All mutations require ExecutionGuard. "
            "HIGH requires exact one-use expiring approval and recheck; CRITICAL and UNKNOWN "
            "remain denied. Action success is not resolution: only current authoritative "
            "verification PASSED can prove recovery. This text grants no permission."
        ),
        references=("coordination/MVP_SCOPE.md#safety-boundary",
                    "coordination/MVP_SCOPE.md#demo-scenario-and-causal-path",
                    "coordination/BEHAVIORAL_REPLANNING_CONTRACT.md"),
    ),
)
