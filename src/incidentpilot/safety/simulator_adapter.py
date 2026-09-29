"""Narrow guarded adapters for the three safe C03 simulator mutations."""

from incidentpilot.contracts import ActionName, ActionRequest
from incidentpilot.safety.guard import GuardedActionExecutor
from incidentpilot.safety.models import SafetyActionRequest
from incidentpilot.simulator import OrderSyncSimulator


def simulator_executors(
    simulator: OrderSyncSimulator,
) -> tuple[GuardedActionExecutor, ...]:
    if not isinstance(simulator, OrderSyncSimulator):
        raise TypeError("simulator must be an OrderSyncSimulator")

    def execute(request: SafetyActionRequest) -> object:
        action = ActionName(request.action)
        simulator_request = ActionRequest(
            incident_id=request.incident_id,
            action=action,
            target=request.target,
        )
        return simulator.execute(simulator_request)

    return tuple(
        GuardedActionExecutor(action.value, execute)
        for action in (
            ActionName.RESTART_NONCRITICAL_WORKER,
            ActionName.CLEAR_APPLICATION_CACHE,
            ActionName.RETRY_SYNC_JOB,
        )
    )
