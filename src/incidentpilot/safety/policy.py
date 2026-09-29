"""Deny-by-default policy evaluation outside any Agent prompt."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Callable, Mapping

from incidentpilot.safety.approvals import ApprovalConsumeResult, ApprovalRegistry
from incidentpilot.safety.catalog import ACTION_CATALOG
from incidentpilot.safety.evidence import SafetyEvidenceRegistry
from incidentpilot.safety.models import (
    ActionScope,
    ActionSpec,
    ApprovalStatus,
    BackupStatus,
    PolicyDecision,
    PolicyEvaluation,
    PolicyReason,
    RiskLevel,
    RollbackStatus,
    SafetyActionRequest,
)
from incidentpilot.safety.usage import ActionUsageRegistry


class SafetyPolicy:
    """Authorize only catalogued, bounded requests with current trusted state."""

    def __init__(
        self,
        approvals: ApprovalRegistry,
        evidence: SafetyEvidenceRegistry,
        *,
        catalog: Mapping[str, ActionSpec] = ACTION_CATALOG,
        usage: ActionUsageRegistry | None = None,
        time_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._approvals = approvals
        self._evidence = evidence
        self._catalog = MappingProxyType(dict(catalog))
        self._usage = usage if usage is not None else ActionUsageRegistry()
        self._time_provider = time_provider or (lambda: datetime.now(timezone.utc))

    @property
    def catalog(self) -> Mapping[str, ActionSpec]:
        return self._catalog

    def evaluate(
        self,
        request: SafetyActionRequest,
        *,
        approval_id: str | None = None,
        now: datetime | None = None,
    ) -> PolicyEvaluation:
        if not isinstance(request, SafetyActionRequest):
            raise TypeError("request must be a SafetyActionRequest")
        evaluation_time = self._validated_now(now)
        spec = self._catalog.get(request.action)
        if spec is None:
            return self._block(
                PolicyReason.UNKNOWN_ACTION,
                "The action is absent from the immutable catalog.",
            )

        if spec.risk is RiskLevel.CRITICAL:
            return self._block(
                PolicyReason.BLOCKED_CRITICAL_ACTION,
                "Critical production-data deletion is never executable in the MVP.",
                risk=spec.risk,
                approval_id=approval_id,
            )

        structural = self._validate_request_bounds(request, spec)
        if structural is not None:
            return structural

        if spec.risk is RiskLevel.LOW:
            maximum = spec.max_executions_per_run
            if maximum is None:
                raise RuntimeError("LOW catalog entry omitted max_executions_per_run")
            if not self._usage.can_execute(request, maximum=maximum):
                return self._block(
                    PolicyReason.ACTION_EXECUTION_LIMIT_REACHED,
                    "The LOW action reached its immutable per-run execution limit.",
                    risk=spec.risk,
                )
            return PolicyEvaluation(
                decision=PolicyDecision.ALLOW,
                reason=PolicyReason.ALLOWED_LOW_RISK_ACTION,
                detail="The LOW request matches the exact catalog bounds.",
                risk=spec.risk,
            )

        if approval_id is None:
            return PolicyEvaluation(
                decision=PolicyDecision.REQUIRE_APPROVAL,
                reason=PolicyReason.APPROVAL_REQUIRED,
                detail="The HIGH request needs an exact, current, one-use approval.",
                risk=spec.risk,
            )

        approval_check = self._validate_approval(
            request,
            spec,
            approval_id=approval_id,
            now=evaluation_time,
        )
        if approval_check is not None:
            return approval_check

        evidence_check = self._validate_safety_evidence(request, spec, approval_id)
        if evidence_check is not None:
            return evidence_check

        return PolicyEvaluation(
            decision=PolicyDecision.ALLOW,
            reason=PolicyReason.ALLOWED_APPROVED_HIGH_RISK_ACTION,
            detail="The HIGH request and trusted safety evidence match the approval bounds.",
            risk=spec.risk,
            approval_id=approval_id,
        )

    def consume_high_risk_approval(
        self,
        approval_id: str,
        *,
        now: datetime | None = None,
    ) -> PolicyEvaluation | None:
        """Atomically consume immediately before execution; return a block if state changed."""
        consume_time = self._validated_now(now)
        result = self._approvals.consume(approval_id, now=consume_time)
        if result is ApprovalConsumeResult.CONSUMED:
            return None
        reasons = {
            ApprovalConsumeResult.NOT_FOUND: PolicyReason.APPROVAL_NOT_FOUND,
            ApprovalConsumeResult.INTEGRITY_FAILED: PolicyReason.APPROVAL_INTEGRITY_FAILED,
            ApprovalConsumeResult.EXPIRED: PolicyReason.APPROVAL_EXPIRED,
            ApprovalConsumeResult.NOT_ACTIVE: PolicyReason.APPROVAL_NOT_ACTIVE,
        }
        return self._block(
            reasons.get(result, PolicyReason.AUTHORIZATION_STATE_CHANGED),
            "The approval changed after evaluation and execution was not started.",
            risk=RiskLevel.HIGH,
            approval_id=approval_id,
        )

    def reserve_low_risk_execution(
        self,
        request: SafetyActionRequest,
    ) -> PolicyEvaluation | None:
        """Atomically reserve one LOW attempt immediately before handler invocation."""
        spec = self._catalog.get(request.action)
        if spec is None or spec.risk is not RiskLevel.LOW:
            raise ValueError("request must name a catalogued LOW action")
        maximum = spec.max_executions_per_run
        if maximum is None:
            raise RuntimeError("LOW catalog entry omitted max_executions_per_run")
        if self._usage.reserve(request, maximum=maximum):
            return None
        return self._block(
            PolicyReason.ACTION_EXECUTION_LIMIT_REACHED,
            "The LOW action limit changed after evaluation and execution was not started.",
            risk=spec.risk,
        )

    def _validate_request_bounds(
        self,
        request: SafetyActionRequest,
        spec: ActionSpec,
    ) -> PolicyEvaluation | None:
        if request.incident_id not in spec.allowed_incident_ids:
            return self._block(
                PolicyReason.INVALID_INCIDENT,
                "The incident is outside the action catalog entry.",
                risk=spec.risk,
            )
        if request.target not in spec.allowed_targets:
            return self._block(
                PolicyReason.INVALID_TARGET,
                "The target is outside the action catalog entry.",
                risk=spec.risk,
            )
        scope_reason = self._scope_failure_reason(request.scope, spec)
        if scope_reason is not None:
            return self._block(
                scope_reason,
                "The requested affected scope is outside the immutable action bounds.",
                risk=spec.risk,
            )
        if not self._arguments_valid(request, spec):
            return self._block(
                PolicyReason.INVALID_ARGUMENTS,
                "The request has a missing, unexpected, or disallowed argument.",
                risk=spec.risk,
            )
        return None

    def _validate_approval(
        self,
        request: SafetyActionRequest,
        spec: ActionSpec,
        *,
        approval_id: str,
        now: datetime,
    ) -> PolicyEvaluation | None:
        approval, integrity_valid = self._approvals.inspect(approval_id)
        if approval is None:
            return self._block(
                PolicyReason.APPROVAL_NOT_FOUND,
                "The approval identifier is not registered.",
                risk=spec.risk,
                approval_id=approval_id,
            )
        if not integrity_valid:
            return self._block(
                PolicyReason.APPROVAL_INTEGRITY_FAILED,
                "The authoritative approval record failed its integrity check.",
                risk=spec.risk,
                approval_id=approval_id,
            )
        if approval.status is not ApprovalStatus.ACTIVE:
            return self._block(
                PolicyReason.APPROVAL_NOT_ACTIVE,
                "The approval is consumed or revoked.",
                risk=spec.risk,
                approval_id=approval_id,
            )
        if now >= approval.expires_at:
            return self._block(
                PolicyReason.APPROVAL_EXPIRED,
                "The approval has expired.",
                risk=spec.risk,
                approval_id=approval_id,
            )
        if not approval.single_use:
            return self._block(
                PolicyReason.APPROVAL_NOT_SINGLE_USE,
                "HIGH approvals must be single-use.",
                risk=spec.risk,
                approval_id=approval_id,
            )
        bindings = (
            (
                approval.run_id == request.run_id,
                PolicyReason.APPROVAL_RUN_MISMATCH,
                "The approval is bound to a different run.",
            ),
            (
                approval.incident_id == request.incident_id,
                PolicyReason.APPROVAL_INCIDENT_MISMATCH,
                "The approval is bound to a different incident.",
            ),
            (
                approval.action == request.action,
                PolicyReason.APPROVAL_ACTION_MISMATCH,
                "The approval is bound to a different action.",
            ),
            (
                approval.target == request.target,
                PolicyReason.APPROVAL_TARGET_MISMATCH,
                "The approval is bound to a different target.",
            ),
            (
                approval.approved_arguments == request.arguments,
                PolicyReason.APPROVAL_ARGUMENTS_MISMATCH,
                "The approval arguments do not exactly match the request.",
            ),
        )
        for matches, reason, detail in bindings:
            if not matches:
                return self._block(
                    reason,
                    detail,
                    risk=spec.risk,
                    approval_id=approval_id,
                )
        if self._scope_failure_reason(approval.approved_scope, spec) is not None:
            return self._block(
                PolicyReason.APPROVAL_SCOPE_EXCEEDED,
                "The approval itself exceeds the action catalog maximum.",
                risk=spec.risk,
                approval_id=approval_id,
            )
        if not approval.approved_scope.covers(request.scope):
            return self._block(
                PolicyReason.APPROVAL_SCOPE_EXCEEDED,
                "The requested scope exceeds the explicit approved resources.",
                risk=spec.risk,
                approval_id=approval_id,
            )
        return None

    def _validate_safety_evidence(
        self,
        request: SafetyActionRequest,
        spec: ActionSpec,
        approval_id: str,
    ) -> PolicyEvaluation | None:
        if spec.requires_backup:
            backup_id = request.evidence.backup_id
            if backup_id is None:
                return self._block(
                    PolicyReason.BACKUP_REQUIRED,
                    "This data mutation requires registered backup evidence.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )
            backup, integrity_valid = self._evidence.inspect_backup(backup_id)
            if backup is None:
                return self._block(
                    PolicyReason.BACKUP_NOT_FOUND,
                    "The backup identifier is not registered.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )
            if not integrity_valid:
                return self._block(
                    PolicyReason.BACKUP_INTEGRITY_FAILED,
                    "The backup record failed its integrity check.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )
            if (backup.run_id, backup.incident_id, backup.target) != (
                request.run_id,
                request.incident_id,
                request.target,
            ):
                return self._block(
                    PolicyReason.BACKUP_BINDING_MISMATCH,
                    "The backup belongs to a different run, incident, or target.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )
            if not backup.covered_scope.covers(request.scope):
                return self._block(
                    PolicyReason.BACKUP_SCOPE_INSUFFICIENT,
                    "The backup does not cover every requested resource.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )
            if backup.status is not BackupStatus.VERIFIED_RECOVERABLE:
                return self._block(
                    PolicyReason.BACKUP_NOT_VERIFIED,
                    "The backup exists but recoverability has not been verified.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )

        if spec.requires_rollback:
            rollback_id = request.evidence.rollback_id
            if rollback_id is None:
                return self._block(
                    PolicyReason.ROLLBACK_REQUIRED,
                    "This action requires registered rollback capability.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )
            rollback, integrity_valid = self._evidence.inspect_rollback(rollback_id)
            if rollback is None:
                return self._block(
                    PolicyReason.ROLLBACK_NOT_FOUND,
                    "The rollback identifier is not registered.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )
            if not integrity_valid:
                return self._block(
                    PolicyReason.ROLLBACK_INTEGRITY_FAILED,
                    "The rollback record failed its integrity check.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )
            if (
                rollback.run_id,
                rollback.incident_id,
                rollback.action,
                rollback.target,
            ) != (request.run_id, request.incident_id, request.action, request.target):
                return self._block(
                    PolicyReason.ROLLBACK_BINDING_MISMATCH,
                    "The rollback capability belongs to a different operation.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )
            if not rollback.covered_scope.covers(request.scope):
                return self._block(
                    PolicyReason.ROLLBACK_SCOPE_INSUFFICIENT,
                    "The rollback capability does not cover every requested resource.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )
            if rollback.status is not RollbackStatus.VERIFIED_READY:
                return self._block(
                    PolicyReason.ROLLBACK_NOT_READY,
                    "Rollback capability exists but is not verified ready.",
                    risk=spec.risk,
                    approval_id=approval_id,
                )
        return None

    @staticmethod
    def _scope_failure_reason(scope: ActionScope, spec: ActionSpec) -> PolicyReason | None:
        if scope.size > spec.max_scope_size:
            return PolicyReason.SCOPE_EXCEEDS_ACTION_LIMIT
        if spec.exact_scope is not None:
            if scope != spec.exact_scope:
                return PolicyReason.SCOPE_EXCEEDS_ACTION_LIMIT
            return None
        if spec.scope_pattern is None:
            return PolicyReason.INVALID_SCOPE
        if not all(re.fullmatch(spec.scope_pattern, resource) for resource in scope.resources):
            return PolicyReason.INVALID_SCOPE
        return None

    @staticmethod
    def _arguments_valid(request: SafetyActionRequest, spec: ActionSpec) -> bool:
        supplied = {argument.name: argument.value for argument in request.arguments}
        rules = {rule.name: rule for rule in spec.argument_rules}
        if set(supplied) - set(rules):
            return False
        if any(rule.required and rule.name not in supplied for rule in spec.argument_rules):
            return False
        return all(value in rules[name].allowed_values for name, value in supplied.items())

    def _validated_now(self, supplied: datetime | None) -> datetime:
        value = supplied or self._time_provider()
        if not isinstance(value, datetime):
            raise TypeError("time provider must return datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("policy time must be timezone-aware")
        return value

    @staticmethod
    def _block(
        reason: PolicyReason,
        detail: str,
        *,
        risk: RiskLevel | None = None,
        approval_id: str | None = None,
    ) -> PolicyEvaluation:
        return PolicyEvaluation(
            decision=PolicyDecision.BLOCK,
            reason=reason,
            detail=detail,
            risk=risk,
            approval_id=approval_id,
        )
