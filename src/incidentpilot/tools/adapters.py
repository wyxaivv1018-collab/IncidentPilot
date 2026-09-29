"""Narrow typed adapters over the read-only simulator surface and C04 guard."""

from __future__ import annotations

from typing import Protocol

from incidentpilot.contracts import (
    EnvironmentState,
    Incident,
    LogFinding,
    VerificationResult,
)
from incidentpilot.safety import (
    ActionArgument,
    ActionScope,
    ExecutionGuard,
    ExecutionGuardResult,
    SafetyActionRequest,
)


class IncidentReadSource(Protocol):
    @property
    def incident(self) -> Incident: ...

    def read_logs(self) -> tuple[LogFinding, ...]: ...

    def read_environment(self) -> EnvironmentState: ...

    def verify_sync(self) -> VerificationResult: ...


class SimulatorReadAdapter:
    """Expose only read methods; no simulator mutation method is reachable here."""

    def __init__(self, source: IncidentReadSource) -> None:
        self._source = source

    def read_incident(self) -> Incident:
        value = self._source.incident
        if not isinstance(value, Incident):
            raise TypeError("incident source returned an invalid Incident")
        return value

    def read_logs(self) -> tuple[LogFinding, ...]:
        value = self._source.read_logs()
        if not isinstance(value, tuple) or not all(
            isinstance(finding, LogFinding) for finding in value
        ):
            raise TypeError("log source returned invalid findings")
        return value

    def read_environment(self) -> EnvironmentState:
        value = self._source.read_environment()
        if not isinstance(value, EnvironmentState):
            raise TypeError("environment source returned an invalid state")
        return value

    def verify_recovery(self) -> VerificationResult:
        value = self._source.verify_sync()
        if not isinstance(value, VerificationResult):
            raise TypeError("verification source returned an invalid result")
        return value


class GuardedActionAdapter:
    """Translate typed Agent requests into the one C04 ExecutionGuard entry point."""

    def __init__(self, guard: ExecutionGuard, *, incident_id: str) -> None:
        if not isinstance(guard, ExecutionGuard):
            raise TypeError("guard must be an ExecutionGuard")
        if not isinstance(incident_id, str) or not incident_id.strip():
            raise ValueError("incident_id must be a non-empty string")
        self._guard = guard
        self._incident_id = incident_id

    def execute(
        self,
        *,
        request_id: str,
        run_id: str,
        action: str,
        target: str,
        arguments: tuple[ActionArgument, ...] = (),
        approval_id: str | None = None,
    ) -> ExecutionGuardResult:
        request = SafetyActionRequest(
            request_id=request_id,
            run_id=run_id,
            incident_id=self._incident_id,
            action=action,
            target=target,
            scope=ActionScope((target,)),
            arguments=arguments,
        )
        return self._guard.execute(request, approval_id=approval_id)

