"""Unified capability-checked execution entry for every state-changing action."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Callable

from incidentpilot.safety.models import (
    ExecutorStatus,
    PolicyDecision,
    PolicyEvaluation,
    PolicyReason,
    RiskLevel,
    SafetyActionRequest,
    SafetyAuditEvent,
)
from incidentpilot.safety.policy import SafetyPolicy


class AuthorizationBypassError(PermissionError):
    """Raised before a handler call when no matching guard capability exists."""


def _request_fingerprint(request: SafetyActionRequest) -> str:
    payload = {
        "request_id": request.request_id,
        "run_id": request.run_id,
        "incident_id": request.incident_id,
        "action": request.action,
        "target": request.target,
        "scope": request.scope.resources,
        "arguments": tuple((item.name, item.value) for item in request.arguments),
        "backup_id": request.evidence.backup_id,
        "rollback_id": request.evidence.rollback_id,
        "schema_version": request.schema_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class _ExecutionCapability:
    authority: object
    action: str
    request_fingerprint: str
    used: bool = False


class GuardedActionExecutor:
    """Wrap one handler so direct calls without a guard-issued capability fail closed."""

    def __init__(self, action: str, handler: Callable[[SafetyActionRequest], object]) -> None:
        if not isinstance(action, str) or not action.strip():
            raise ValueError("executor action must be a non-empty string")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self.action = action
        self._handler = handler
        self._authority: object | None = None

    def _bind(self, authority: object) -> None:
        if self._authority is not None:
            raise ValueError(f"executor is already bound: {self.action}")
        self._authority = authority

    def execute(self, request: SafetyActionRequest, capability: object) -> object:
        if not isinstance(request, SafetyActionRequest):
            raise TypeError("request must be a SafetyActionRequest")
        if not isinstance(capability, _ExecutionCapability):
            raise AuthorizationBypassError("executor requires a guard-issued capability")
        if self._authority is None or capability.authority is not self._authority:
            raise AuthorizationBypassError("capability was not issued by this execution guard")
        if capability.used:
            raise AuthorizationBypassError("execution capability has already been used")
        if capability.action != self.action or request.action != self.action:
            raise AuthorizationBypassError("execution capability is bound to a different action")
        if capability.request_fingerprint != _request_fingerprint(request):
            raise AuthorizationBypassError("request changed after policy authorization")
        capability.used = True
        return self._handler(request)


@dataclass(frozen=True, slots=True)
class ExecutionGuardResult:
    evaluation: PolicyEvaluation
    audit_event: SafetyAuditEvent
    executor_result: object | None = None

    @property
    def executed(self) -> bool:
        return self.audit_event.executed


class ExecutionGuard:
    """Evaluate, atomically consume HIGH approval, then mint one execution capability."""

    def __init__(
        self,
        policy: SafetyPolicy,
        executors: tuple[GuardedActionExecutor, ...],
    ) -> None:
        if not isinstance(policy, SafetyPolicy):
            raise TypeError("policy must be a SafetyPolicy")
        if not isinstance(executors, tuple) or not all(
            isinstance(executor, GuardedActionExecutor) for executor in executors
        ):
            raise TypeError("executors must be a tuple of GuardedActionExecutor values")
        actions = [executor.action for executor in executors]
        if len(set(actions)) != len(actions):
            raise ValueError("executor actions must be unique")
        self._policy = policy
        self._authority = object()
        self._executors = {executor.action: executor for executor in executors}
        for executor in executors:
            executor._bind(self._authority)
        self._audit_events: list[SafetyAuditEvent] = []
        self._audit_lock = Lock()
        self._event_number = 0

    @property
    def audit_events(self) -> tuple[SafetyAuditEvent, ...]:
        with self._audit_lock:
            return tuple(self._audit_events)

    def execute(
        self,
        request: SafetyActionRequest,
        *,
        approval_id: str | None = None,
        now: datetime | None = None,
    ) -> ExecutionGuardResult:
        evaluation = self._policy.evaluate(request, approval_id=approval_id, now=now)
        if evaluation.decision is not PolicyDecision.ALLOW:
            return self._result(
                request,
                evaluation,
                executor_status=ExecutorStatus.NOT_STARTED,
            )

        executor = self._executors.get(request.action)
        if executor is None:
            missing = PolicyEvaluation(
                decision=PolicyDecision.BLOCK,
                reason=PolicyReason.EXECUTOR_NOT_CONFIGURED,
                detail="No guarded executor is configured for this authorized action.",
                risk=evaluation.risk,
                approval_id=approval_id,
            )
            return self._result(
                request,
                missing,
                executor_status=ExecutorStatus.NOT_STARTED,
            )

        if evaluation.risk is RiskLevel.HIGH:
            if approval_id is None:
                raise RuntimeError("HIGH ALLOW result omitted approval_id")
            changed = self._policy.consume_high_risk_approval(approval_id, now=now)
            if changed is not None:
                return self._result(
                    request,
                    changed,
                    executor_status=ExecutorStatus.NOT_STARTED,
                )
        elif evaluation.risk is RiskLevel.LOW:
            changed = self._policy.reserve_low_risk_execution(request)
            if changed is not None:
                return self._result(
                    request,
                    changed,
                    executor_status=ExecutorStatus.NOT_STARTED,
                )

        capability = _ExecutionCapability(
            authority=self._authority,
            action=request.action,
            request_fingerprint=_request_fingerprint(request),
        )
        try:
            executor_result = executor.execute(request, capability)
        except Exception:
            self._record_event(
                request,
                evaluation,
                executor_status=ExecutorStatus.RAISED,
            )
            raise
        return self._result(
            request,
            evaluation,
            executor_status=ExecutorStatus.RETURNED,
            executor_result=executor_result,
        )

    def _result(
        self,
        request: SafetyActionRequest,
        evaluation: PolicyEvaluation,
        *,
        executor_status: ExecutorStatus,
        executor_result: object | None = None,
    ) -> ExecutionGuardResult:
        event = self._record_event(
            request,
            evaluation,
            executor_status=executor_status,
        )
        return ExecutionGuardResult(
            evaluation=evaluation,
            audit_event=event,
            executor_result=executor_result,
        )

    def _record_event(
        self,
        request: SafetyActionRequest,
        evaluation: PolicyEvaluation,
        *,
        executor_status: ExecutorStatus,
    ) -> SafetyAuditEvent:
        with self._audit_lock:
            self._event_number += 1
            event = SafetyAuditEvent(
                event_id=f"SAFETY-{self._event_number:06d}",
                request_id=request.request_id,
                run_id=request.run_id,
                action=request.action,
                target=request.target,
                decision=evaluation.decision,
                reason=evaluation.reason,
                executor_status=executor_status,
                approval_id=evaluation.approval_id,
            )
            self._audit_events.append(event)
            return event
