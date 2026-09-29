"""Server-owned pending approvals bound to the existing C04 registry."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Condition, RLock
from typing import Callable
from uuid import uuid4

from incidentpilot.api.contracts import ApiError, ApiErrorCode, StringEnum
from incidentpilot.safety import (
    ActionArgument,
    ActionScope,
    ApprovalRegistry,
    PolicyDecision,
    RiskLevel,
    SafetyActionRequest,
    SafetyEvidenceRegistry,
    SafetyPolicy,
)


class PendingApprovalStatus(StringEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class _PendingApproval:
    approval_request_id: str
    request: SafetyActionRequest
    created_at: datetime
    expires_at: datetime
    status: PendingApprovalStatus = PendingApprovalStatus.PENDING
    approval_id: str | None = None


class ApprovalCoordinator:
    """Approve only an exact operation previously registered by trusted run code."""

    def __init__(
        self,
        approvals: ApprovalRegistry,
        evidence: SafetyEvidenceRegistry,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        approved_by: str = "local-demo-user",
    ) -> None:
        if not isinstance(approvals, ApprovalRegistry):
            raise TypeError("approvals must be an ApprovalRegistry")
        if not isinstance(evidence, SafetyEvidenceRegistry):
            raise TypeError("evidence must be a SafetyEvidenceRegistry")
        if not isinstance(approved_by, str) or not approved_by.strip():
            raise ValueError("approved_by must be a non-empty string")
        self._approvals = approvals
        self._policy = SafetyPolicy(approvals, evidence)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: f"APRQ-{uuid4().hex}")
        self._approved_by = approved_by.strip()
        self._records: dict[str, _PendingApproval] = {}
        self._cancelled_run_ids: set[str] = set()
        self._lock = RLock()
        self._condition = Condition(self._lock)

    def register(
        self,
        request: SafetyActionRequest,
        *,
        ttl_seconds: float = 60.0,
    ) -> dict[str, object]:
        if not isinstance(request, SafetyActionRequest):
            raise TypeError("request must be a SafetyActionRequest")
        if not isinstance(ttl_seconds, (int, float)) or not 1 <= ttl_seconds <= 300:
            raise ValueError("ttl_seconds must be between 1 and 300")
        now = self._now()
        evaluation = self._policy.evaluate(request, now=now)
        if (
            evaluation.decision is not PolicyDecision.REQUIRE_APPROVAL
            or evaluation.risk is not RiskLevel.HIGH
        ):
            raise ValueError("only a valid catalogued HIGH request may become pending")
        record = _PendingApproval(
            approval_request_id=self._id_factory(),
            request=request,
            created_at=now,
            expires_at=now + timedelta(seconds=float(ttl_seconds)),
        )
        with self._condition:
            if request.run_id in self._cancelled_run_ids:
                raise ApiError(
                    status_code=409,
                    code=ApiErrorCode.APPROVAL_NOT_AVAILABLE,
                    message="Cancelled runs cannot register new approval requests.",
                )
            if record.approval_request_id in self._records:
                raise ValueError("approval request identifier already exists")
            self._records[record.approval_request_id] = record
            self._condition.notify_all()
            return self._view(record)

    def approve(
        self,
        *,
        run_id: str,
        approval_request_id: str,
        action: str,
        target: str,
        scope: ActionScope,
        arguments: tuple[ActionArgument, ...],
    ) -> dict[str, object]:
        now = self._now()
        with self._condition:
            if run_id in self._cancelled_run_ids:
                raise ApiError(
                    status_code=409,
                    code=ApiErrorCode.APPROVAL_NOT_AVAILABLE,
                    message="Cancelled runs cannot receive approvals.",
                )
            record = self._records.get(approval_request_id)
            if record is None or record.request.run_id != run_id:
                raise ApiError(
                    status_code=404,
                    code=ApiErrorCode.APPROVAL_REQUEST_NOT_FOUND,
                    message="The pending approval request was not found for this run.",
                )
            self._expire_if_needed(record, now)
            if record.status is PendingApprovalStatus.EXPIRED:
                raise ApiError(
                    status_code=410,
                    code=ApiErrorCode.APPROVAL_EXPIRED,
                    message="The pending approval request has expired and must be reissued.",
                )
            if record.status is PendingApprovalStatus.APPROVED:
                raise ApiError(
                    status_code=409,
                    code=ApiErrorCode.APPROVAL_ALREADY_USED,
                    message="This pending approval request has already been approved.",
                )
            if record.status is not PendingApprovalStatus.PENDING:
                raise ApiError(
                    status_code=409,
                    code=ApiErrorCode.APPROVAL_NOT_AVAILABLE,
                    message="This approval request is no longer available.",
                )
            canonical = record.request
            if (
                action != canonical.action
                or target != canonical.target
                or scope != canonical.scope
                or arguments != canonical.arguments
            ):
                raise ApiError(
                    status_code=409,
                    code=ApiErrorCode.APPROVAL_BINDING_MISMATCH,
                    message=(
                        "Approval confirmation must exactly match the pending action, target, "
                        "scope, and arguments."
                    ),
                )
            approval = self._approvals.issue(
                run_id=canonical.run_id,
                incident_id=canonical.incident_id,
                action=canonical.action,
                target=canonical.target,
                approved_scope=canonical.scope,
                approved_arguments=canonical.arguments,
                approved_by=self._approved_by,
                issued_at=now,
                expires_at=record.expires_at,
                single_use=True,
            )
            record.status = PendingApprovalStatus.APPROVED
            record.approval_id = approval.approval_id
            self._condition.notify_all()
            return self._view(record)

    def wait_for_approval(
        self,
        approval_request_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> str | None:
        if timeout_seconds is not None and (
            not isinstance(timeout_seconds, (int, float)) or timeout_seconds < 0
        ):
            raise ValueError("timeout_seconds must be non-negative or None")
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        with self._condition:
            while True:
                record = self._records.get(approval_request_id)
                if record is None:
                    return None
                self._expire_if_needed(record, self._now())
                if record.status is PendingApprovalStatus.APPROVED:
                    return record.approval_id
                if record.status in {
                    PendingApprovalStatus.EXPIRED,
                    PendingApprovalStatus.CANCELLED,
                }:
                    return None
                wait_for = None
                if deadline is not None:
                    wait_for = deadline - time.monotonic()
                    if wait_for <= 0:
                        return None
                self._condition.wait(wait_for)

    def for_run(self, run_id: str) -> tuple[dict[str, object], ...]:
        now = self._now()
        with self._condition:
            records = [record for record in self._records.values() if record.request.run_id == run_id]
            for record in records:
                self._expire_if_needed(record, now)
            return tuple(self._view(record) for record in records)

    def cancel_run(self, run_id: str) -> None:
        with self._condition:
            self._cancelled_run_ids.add(run_id)
            self._approvals.cancel_run(run_id)
            for record in self._records.values():
                if record.request.run_id != run_id:
                    continue
                if record.status is PendingApprovalStatus.PENDING:
                    record.status = PendingApprovalStatus.CANCELLED
                elif record.status is PendingApprovalStatus.APPROVED:
                    record.status = PendingApprovalStatus.CANCELLED
            self._condition.notify_all()

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("approval clock must return datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approval clock must return a timezone-aware datetime")
        return value

    def _expire_if_needed(self, record: _PendingApproval, now: datetime) -> None:
        if record.status is PendingApprovalStatus.PENDING and now >= record.expires_at:
            record.status = PendingApprovalStatus.EXPIRED
            self._condition.notify_all()

    @staticmethod
    def _view(record: _PendingApproval) -> dict[str, object]:
        return {
            "approval_request_id": record.approval_request_id,
            "run_id": record.request.run_id,
            "action": record.request.action,
            "target": record.request.target,
            "scope": list(record.request.scope.resources),
            "arguments": {
                argument.name: argument.value for argument in record.request.arguments
            },
            "risk": RiskLevel.HIGH.value,
            "status": record.status.value,
            "created_at": record.created_at.isoformat(),
            "expires_at": record.expires_at.isoformat(),
            "approval_id": record.approval_id,
            "single_use": True,
        }
