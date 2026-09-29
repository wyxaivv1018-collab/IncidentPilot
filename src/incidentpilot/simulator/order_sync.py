"""Deterministic, side-effect-free order-sync incident environment."""

from __future__ import annotations

from dataclasses import dataclass, field

from incidentpilot.contracts import (
    ActionName,
    ActionOutcome,
    ActionRequest,
    ActionResult,
    CacheLockStatus,
    DatabaseStatus,
    EnvironmentState,
    Incident,
    LogFinding,
    SyncJobStatus,
    VerificationResult,
    VerificationStatus,
    WorkerStatus,
)
from incidentpilot.simulator.fixtures import (
    CACHE_LOCK_FINDING,
    CACHE_TARGET,
    INCIDENT_ID,
    ORDER_SYNC_INCIDENT,
    SYNC_JOB_TARGET,
    SYNC_TIMEOUT_FINDING,
    WORKER_TARGET,
)


class InvalidActionRequest(ValueError):
    """Raised when a request is outside this simulator's immutable bounds."""


@dataclass(slots=True)
class _MutableEnvironment:
    worker_status: WorkerStatus = WorkerStatus.STOPPED
    database_status: DatabaseStatus = DatabaseStatus.HEALTHY
    cache_lock_exists: bool = True
    sync_job_status: SyncJobStatus = SyncJobStatus.FAILED
    visible_logs: list[LogFinding] = field(default_factory=lambda: [SYNC_TIMEOUT_FINDING])
    executed_actions: list[ActionRequest] = field(default_factory=list)


EXPECTED_TARGETS = {
    ActionName.RESTART_NONCRITICAL_WORKER: WORKER_TARGET,
    ActionName.CLEAR_APPLICATION_CACHE: CACHE_TARGET,
    ActionName.RETRY_SYNC_JOB: SYNC_JOB_TARGET,
}


class OrderSyncSimulator:
    """Compute outcomes from current causal state, never from a scripted step number."""

    def __init__(self) -> None:
        self._state = _MutableEnvironment()

    @property
    def incident(self) -> Incident:
        return ORDER_SYNC_INCIDENT

    def reset(self) -> EnvironmentState:
        """Restore the exact logical fixture state and return its observable snapshot."""
        self._state = _MutableEnvironment()
        return self.read_environment()

    def read_logs(self) -> tuple[LogFinding, ...]:
        return tuple(self._state.visible_logs)

    def read_environment(self) -> EnvironmentState:
        return EnvironmentState(
            incident_id=INCIDENT_ID,
            worker_status=self._state.worker_status,
            database_status=self._state.database_status,
            cache_lock=self._observable_cache_lock(),
            sync_job_status=self._state.sync_job_status,
            visible_logs=self.read_logs(),
            executed_actions=tuple(self._state.executed_actions),
        )

    def verify_sync(self) -> VerificationResult:
        state = self.read_environment()
        if state.sync_job_status is SyncJobStatus.SUCCESS:
            return VerificationResult(
                incident_id=INCIDENT_ID,
                status=VerificationStatus.PASSED,
                detail="The synthetic order synchronization is successful.",
                state=state,
                evidence=state.visible_logs,
            )
        return VerificationResult(
            incident_id=INCIDENT_ID,
            status=VerificationStatus.FAILED,
            detail="The synthetic order synchronization remains failed.",
            state=state,
            evidence=state.visible_logs,
        )

    def execute(self, request: ActionRequest) -> ActionResult:
        """Execute one bounded action after validating its incident and target."""
        self._validate_request(request)
        self._state.executed_actions.append(request)

        if request.action is ActionName.RESTART_NONCRITICAL_WORKER:
            return self._restart_worker(request)
        if request.action is ActionName.CLEAR_APPLICATION_CACHE:
            return self._clear_cache(request)
        if request.action is ActionName.RETRY_SYNC_JOB:
            return self._retry_sync(request)
        raise InvalidActionRequest(f"unsupported action: {request.action}")

    def _validate_request(self, request: ActionRequest) -> None:
        if not isinstance(request, ActionRequest):
            raise TypeError("request must be an ActionRequest")
        if request.incident_id != INCIDENT_ID:
            raise InvalidActionRequest("request incident does not match the loaded fixture")
        expected_target = EXPECTED_TARGETS.get(request.action)
        if expected_target is None:
            raise InvalidActionRequest(f"unsupported action: {request.action}")
        if request.target != expected_target:
            raise InvalidActionRequest(
                f"invalid target for {request.action.value}: expected {expected_target}"
            )

    def _restart_worker(self, request: ActionRequest) -> ActionResult:
        if self._state.worker_status is WorkerStatus.RUNNING:
            return self._result(
                request,
                ActionOutcome.REJECTED,
                "The synthetic sync-worker is already running; state was unchanged.",
            )
        self._state.worker_status = WorkerStatus.RUNNING
        return self._result(
            request,
            ActionOutcome.SUCCEEDED,
            "The synthetic sync-worker changed from stopped to running.",
        )

    def _clear_cache(self, request: ActionRequest) -> ActionResult:
        if not self._state.cache_lock_exists:
            return self._result(
                request,
                ActionOutcome.REJECTED,
                "The bounded application cache namespace is already clear; state was unchanged.",
            )
        self._state.cache_lock_exists = False
        return self._result(
            request,
            ActionOutcome.SUCCEEDED,
            "The bounded order-sync application cache namespace is clear.",
        )

    def _retry_sync(self, request: ActionRequest) -> ActionResult:
        if self._state.sync_job_status is SyncJobStatus.SUCCESS:
            return self._result(
                request,
                ActionOutcome.REJECTED,
                "The synthetic order synchronization already succeeded; state was unchanged.",
            )

        if self._state.worker_status is WorkerStatus.STOPPED:
            self._state.sync_job_status = SyncJobStatus.FAILED
            return self._result(
                request,
                ActionOutcome.FAILED,
                "The order synchronization failed because sync-worker is stopped.",
            )

        if self._state.cache_lock_exists:
            new_findings: tuple[LogFinding, ...] = ()
            if CACHE_LOCK_FINDING not in self._state.visible_logs:
                self._state.visible_logs.append(CACHE_LOCK_FINDING)
                new_findings = (CACHE_LOCK_FINDING,)
            self._state.sync_job_status = SyncJobStatus.FAILED
            return self._result(
                request,
                ActionOutcome.FAILED,
                "The order synchronization failed because the application cache lock is present.",
                new_findings,
            )

        self._state.sync_job_status = SyncJobStatus.SUCCESS
        return self._result(
            request,
            ActionOutcome.SUCCEEDED,
            "The synthetic order synchronization completed successfully.",
        )

    def _observable_cache_lock(self) -> CacheLockStatus:
        if not self._state.cache_lock_exists:
            return CacheLockStatus.CLEARED
        if CACHE_LOCK_FINDING in self._state.visible_logs:
            return CacheLockStatus.PRESENT
        return CacheLockStatus.UNKNOWN

    def _result(
        self,
        request: ActionRequest,
        outcome: ActionOutcome,
        detail: str,
        new_findings: tuple[LogFinding, ...] = (),
    ) -> ActionResult:
        return ActionResult(
            request=request,
            outcome=outcome,
            detail=detail,
            state=self.read_environment(),
            new_findings=new_findings,
        )
