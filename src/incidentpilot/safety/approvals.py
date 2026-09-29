"""Authoritative, integrity-checked, single-use approval registry."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from incidentpilot.safety.models import (
    ActionArgument,
    ActionScope,
    Approval,
    ApprovalStatus,
    StringEnum,
)


class ApprovalConsumeResult(StringEnum):
    CONSUMED = "CONSUMED"
    NOT_FOUND = "NOT_FOUND"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"
    EXPIRED = "EXPIRED"
    NOT_ACTIVE = "NOT_ACTIVE"


def _approval_payload(approval: Approval) -> bytes:
    data = {
        "approval_id": approval.approval_id,
        "run_id": approval.run_id,
        "incident_id": approval.incident_id,
        "action": approval.action,
        "target": approval.target,
        "approved_scope": approval.approved_scope.resources,
        "approved_arguments": tuple(
            (argument.name, argument.value) for argument in approval.approved_arguments
        ),
        "approved_by": approval.approved_by,
        "status": approval.status.value,
        "issued_at": approval.issued_at.isoformat(),
        "expires_at": approval.expires_at.isoformat(),
        "single_use": approval.single_use,
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ApprovalRegistry:
    """Keep the canonical grant state outside caller-controlled requests."""

    def __init__(self) -> None:
        self._approvals: dict[str, Approval] = {}
        self._integrity_tags: dict[str, bytes] = {}
        self._cancelled_run_ids: set[str] = set()
        self._seal_key = secrets.token_bytes(32)
        self._lock = RLock()

    def issue(
        self,
        *,
        run_id: str,
        incident_id: str,
        action: str,
        target: str,
        approved_scope: ActionScope,
        approved_arguments: tuple[ActionArgument, ...],
        approved_by: str,
        expires_at: datetime,
        issued_at: datetime | None = None,
        approval_id: str | None = None,
        single_use: bool = True,
    ) -> Approval:
        issued = issued_at or datetime.now(timezone.utc)
        approval = Approval(
            approval_id=approval_id or f"APR-{uuid4().hex}",
            run_id=run_id,
            incident_id=incident_id,
            action=action,
            target=target,
            approved_scope=approved_scope,
            approved_arguments=approved_arguments,
            approved_by=approved_by,
            status=ApprovalStatus.ACTIVE,
            issued_at=issued,
            expires_at=expires_at,
            single_use=single_use,
        )
        with self._lock:
            if approval.run_id in self._cancelled_run_ids:
                raise ValueError("cancelled runs cannot receive approvals")
            if approval.approval_id in self._approvals:
                raise ValueError(f"approval already exists: {approval.approval_id}")
            self._store(approval)
        return approval

    def inspect(self, approval_id: str) -> tuple[Approval | None, bool]:
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None:
                return None, True
            return approval, self._has_valid_integrity(approval)

    def consume(self, approval_id: str, *, now: datetime) -> ApprovalConsumeResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None:
                return ApprovalConsumeResult.NOT_FOUND
            if not self._has_valid_integrity(approval):
                return ApprovalConsumeResult.INTEGRITY_FAILED
            if approval.run_id in self._cancelled_run_ids:
                return ApprovalConsumeResult.NOT_ACTIVE
            if approval.status is not ApprovalStatus.ACTIVE:
                return ApprovalConsumeResult.NOT_ACTIVE
            if now >= approval.expires_at:
                return ApprovalConsumeResult.EXPIRED
            self._store(replace(approval, status=ApprovalStatus.CONSUMED))
            return ApprovalConsumeResult.CONSUMED

    def revoke(self, approval_id: str) -> Approval:
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None:
                raise KeyError(approval_id)
            if not self._has_valid_integrity(approval):
                raise ValueError("approval integrity check failed")
            if approval.status is not ApprovalStatus.ACTIVE:
                return approval
            revoked = replace(approval, status=ApprovalStatus.REVOKED)
            self._store(revoked)
            return revoked

    def cancel_run(self, run_id: str) -> None:
        """Atomically tombstone a run and revoke only its still-active grants."""
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        with self._lock:
            self._cancelled_run_ids.add(run_id)
            for approval in tuple(self._approvals.values()):
                if (
                    approval.run_id == run_id
                    and self._has_valid_integrity(approval)
                    and approval.status is ApprovalStatus.ACTIVE
                ):
                    self._store(replace(approval, status=ApprovalStatus.REVOKED))

    def _store(self, approval: Approval) -> None:
        self._approvals[approval.approval_id] = approval
        self._integrity_tags[approval.approval_id] = hmac.new(
            self._seal_key,
            _approval_payload(approval),
            hashlib.sha256,
        ).digest()

    def _has_valid_integrity(self, approval: Approval) -> bool:
        expected = self._integrity_tags.get(approval.approval_id)
        if expected is None:
            return False
        actual = hmac.new(
            self._seal_key,
            _approval_payload(approval),
            hashlib.sha256,
        ).digest()
        return hmac.compare_digest(expected, actual)
