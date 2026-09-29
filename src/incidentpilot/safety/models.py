"""Immutable contracts for programmatic action authorization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

SAFETY_SCHEMA_VERSION = "1.0"


class StringEnum(str, Enum):
    """A Python 3.10-compatible string enum."""

    def __str__(self) -> str:
        return self.value


class RiskLevel(StringEnum):
    LOW = "LOW"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PolicyDecision(StringEnum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    BLOCK = "BLOCK"


class PolicyReason(StringEnum):
    ALLOWED_LOW_RISK_ACTION = "ALLOWED_LOW_RISK_ACTION"
    ALLOWED_APPROVED_HIGH_RISK_ACTION = "ALLOWED_APPROVED_HIGH_RISK_ACTION"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    BLOCKED_CRITICAL_ACTION = "BLOCKED_CRITICAL_ACTION"
    INVALID_INCIDENT = "INVALID_INCIDENT"
    INVALID_TARGET = "INVALID_TARGET"
    INVALID_SCOPE = "INVALID_SCOPE"
    SCOPE_EXCEEDS_ACTION_LIMIT = "SCOPE_EXCEEDS_ACTION_LIMIT"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    ACTION_EXECUTION_LIMIT_REACHED = "ACTION_EXECUTION_LIMIT_REACHED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_NOT_FOUND = "APPROVAL_NOT_FOUND"
    APPROVAL_INTEGRITY_FAILED = "APPROVAL_INTEGRITY_FAILED"
    APPROVAL_NOT_ACTIVE = "APPROVAL_NOT_ACTIVE"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_NOT_SINGLE_USE = "APPROVAL_NOT_SINGLE_USE"
    APPROVAL_RUN_MISMATCH = "APPROVAL_RUN_MISMATCH"
    APPROVAL_INCIDENT_MISMATCH = "APPROVAL_INCIDENT_MISMATCH"
    APPROVAL_ACTION_MISMATCH = "APPROVAL_ACTION_MISMATCH"
    APPROVAL_TARGET_MISMATCH = "APPROVAL_TARGET_MISMATCH"
    APPROVAL_ARGUMENTS_MISMATCH = "APPROVAL_ARGUMENTS_MISMATCH"
    APPROVAL_SCOPE_EXCEEDED = "APPROVAL_SCOPE_EXCEEDED"
    BACKUP_REQUIRED = "BACKUP_REQUIRED"
    BACKUP_NOT_FOUND = "BACKUP_NOT_FOUND"
    BACKUP_INTEGRITY_FAILED = "BACKUP_INTEGRITY_FAILED"
    BACKUP_NOT_VERIFIED = "BACKUP_NOT_VERIFIED"
    BACKUP_BINDING_MISMATCH = "BACKUP_BINDING_MISMATCH"
    BACKUP_SCOPE_INSUFFICIENT = "BACKUP_SCOPE_INSUFFICIENT"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"
    ROLLBACK_NOT_FOUND = "ROLLBACK_NOT_FOUND"
    ROLLBACK_INTEGRITY_FAILED = "ROLLBACK_INTEGRITY_FAILED"
    ROLLBACK_NOT_READY = "ROLLBACK_NOT_READY"
    ROLLBACK_BINDING_MISMATCH = "ROLLBACK_BINDING_MISMATCH"
    ROLLBACK_SCOPE_INSUFFICIENT = "ROLLBACK_SCOPE_INSUFFICIENT"
    EXECUTOR_NOT_CONFIGURED = "EXECUTOR_NOT_CONFIGURED"
    AUTHORIZATION_STATE_CHANGED = "AUTHORIZATION_STATE_CHANGED"


class ApprovalStatus(StringEnum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"


class BackupStatus(StringEnum):
    CREATED = "CREATED"
    VERIFIED_RECOVERABLE = "VERIFIED_RECOVERABLE"


class RollbackStatus(StringEnum):
    DECLARED = "DECLARED"
    VERIFIED_READY = "VERIFIED_READY"


class ExecutorStatus(StringEnum):
    NOT_STARTED = "NOT_STARTED"
    RETURNED = "RETURNED"
    RAISED = "RAISED"


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _require_optional_identifier(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_non_empty(value, field_name)


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ActionArgument:
    name: str
    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.name, "argument name")
        _require_non_empty(self.value, f"argument {self.name}")


@dataclass(frozen=True, slots=True)
class ActionScope:
    """Explicit resources affected by one request; count is derived, never asserted."""

    resources: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.resources, tuple):
            raise TypeError("scope resources must be a tuple")
        if not self.resources:
            raise ValueError("scope resources must not be empty")
        for resource in self.resources:
            _require_non_empty(resource, "scope resource")
        if len(set(self.resources)) != len(self.resources):
            raise ValueError("scope resources must be unique")
        object.__setattr__(self, "resources", tuple(sorted(self.resources)))

    @property
    def size(self) -> int:
        return len(self.resources)

    def covers(self, requested: ActionScope) -> bool:
        if not isinstance(requested, ActionScope):
            raise TypeError("requested must be an ActionScope")
        return set(requested.resources).issubset(self.resources)


@dataclass(frozen=True, slots=True)
class SafetyEvidenceReferences:
    backup_id: str | None = None
    rollback_id: str | None = None

    def __post_init__(self) -> None:
        _require_optional_identifier(self.backup_id, "backup_id")
        _require_optional_identifier(self.rollback_id, "rollback_id")


@dataclass(frozen=True, slots=True)
class SafetyActionRequest:
    request_id: str
    run_id: str
    incident_id: str
    action: str
    target: str
    scope: ActionScope
    arguments: tuple[ActionArgument, ...] = ()
    evidence: SafetyEvidenceReferences = field(default_factory=SafetyEvidenceReferences)
    schema_version: str = SAFETY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "run_id",
            "incident_id",
            "action",
            "target",
            "schema_version",
        ):
            _require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.scope, ActionScope):
            raise TypeError("scope must be an ActionScope")
        if not isinstance(self.arguments, tuple) or not all(
            isinstance(argument, ActionArgument) for argument in self.arguments
        ):
            raise TypeError("arguments must be a tuple of ActionArgument values")
        names = [argument.name for argument in self.arguments]
        if len(set(names)) != len(names):
            raise ValueError("argument names must be unique")
        object.__setattr__(self, "arguments", tuple(sorted(self.arguments, key=lambda item: item.name)))
        if not isinstance(self.evidence, SafetyEvidenceReferences):
            raise TypeError("evidence must be SafetyEvidenceReferences")


@dataclass(frozen=True, slots=True)
class ArgumentRule:
    name: str
    allowed_values: tuple[str, ...]
    required: bool = True

    def __post_init__(self) -> None:
        _require_non_empty(self.name, "argument rule name")
        if not isinstance(self.allowed_values, tuple) or not self.allowed_values:
            raise ValueError("allowed_values must be a non-empty tuple")
        for value in self.allowed_values:
            _require_non_empty(value, f"allowed value for {self.name}")
        if len(set(self.allowed_values)) != len(self.allowed_values):
            raise ValueError("allowed argument values must be unique")


@dataclass(frozen=True, slots=True)
class ActionSpec:
    action: str
    risk: RiskLevel
    allowed_incident_ids: tuple[str, ...]
    allowed_targets: tuple[str, ...]
    max_scope_size: int
    exact_scope: ActionScope | None = None
    scope_pattern: str | None = None
    argument_rules: tuple[ArgumentRule, ...] = ()
    max_executions_per_run: int | None = None
    requires_backup: bool = False
    requires_rollback: bool = False

    def __post_init__(self) -> None:
        _require_non_empty(self.action, "action")
        if not isinstance(self.risk, RiskLevel):
            raise TypeError("risk must be a RiskLevel")
        for field_name in ("allowed_incident_ids", "allowed_targets"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not values:
                raise ValueError(f"{field_name} must be a non-empty tuple")
            for value in values:
                _require_non_empty(value, field_name)
        if not isinstance(self.max_scope_size, int) or self.max_scope_size < 1:
            raise ValueError("max_scope_size must be a positive integer")
        if self.exact_scope is not None and not isinstance(self.exact_scope, ActionScope):
            raise TypeError("exact_scope must be an ActionScope")
        if self.exact_scope is not None and self.scope_pattern is not None:
            raise ValueError("choose exact_scope or scope_pattern, not both")
        if self.exact_scope is None and self.scope_pattern is None:
            raise ValueError("an exact_scope or scope_pattern is required")
        if not isinstance(self.argument_rules, tuple) or not all(
            isinstance(rule, ArgumentRule) for rule in self.argument_rules
        ):
            raise TypeError("argument_rules must be a tuple of ArgumentRule values")
        if self.max_executions_per_run is not None and (
            not isinstance(self.max_executions_per_run, int)
            or self.max_executions_per_run < 1
        ):
            raise ValueError("max_executions_per_run must be a positive integer or None")
        if self.risk is RiskLevel.LOW and self.max_executions_per_run is None:
            raise ValueError("LOW actions require max_executions_per_run")


@dataclass(frozen=True, slots=True)
class Approval:
    approval_id: str
    run_id: str
    incident_id: str
    action: str
    target: str
    approved_scope: ActionScope
    approved_arguments: tuple[ActionArgument, ...]
    approved_by: str
    status: ApprovalStatus
    issued_at: datetime
    expires_at: datetime
    single_use: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "approval_id",
            "run_id",
            "incident_id",
            "action",
            "target",
            "approved_by",
        ):
            _require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.approved_scope, ActionScope):
            raise TypeError("approved_scope must be an ActionScope")
        if not isinstance(self.approved_arguments, tuple) or not all(
            isinstance(argument, ActionArgument) for argument in self.approved_arguments
        ):
            raise TypeError("approved_arguments must be a tuple of ActionArgument values")
        names = [argument.name for argument in self.approved_arguments]
        if len(set(names)) != len(names):
            raise ValueError("approved argument names must be unique")
        object.__setattr__(
            self,
            "approved_arguments",
            tuple(sorted(self.approved_arguments, key=lambda item: item.name)),
        )
        if not isinstance(self.status, ApprovalStatus):
            raise TypeError("status must be an ApprovalStatus")
        _require_aware_datetime(self.issued_at, "issued_at")
        _require_aware_datetime(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if not isinstance(self.single_use, bool):
            raise TypeError("single_use must be a bool")


@dataclass(frozen=True, slots=True)
class BackupEvidence:
    backup_id: str
    run_id: str
    incident_id: str
    target: str
    covered_scope: ActionScope
    status: BackupStatus
    created_at: datetime
    verified_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("backup_id", "run_id", "incident_id", "target"):
            _require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.covered_scope, ActionScope):
            raise TypeError("covered_scope must be an ActionScope")
        if not isinstance(self.status, BackupStatus):
            raise TypeError("status must be a BackupStatus")
        _require_aware_datetime(self.created_at, "created_at")
        if self.verified_at is not None:
            _require_aware_datetime(self.verified_at, "verified_at")
            if self.verified_at < self.created_at:
                raise ValueError("verified_at must not precede created_at")
        if self.status is BackupStatus.VERIFIED_RECOVERABLE and self.verified_at is None:
            raise ValueError("recoverable backup evidence requires verified_at")


@dataclass(frozen=True, slots=True)
class RollbackEvidence:
    rollback_id: str
    run_id: str
    incident_id: str
    action: str
    target: str
    covered_scope: ActionScope
    status: RollbackStatus
    declared_at: datetime
    verified_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("rollback_id", "run_id", "incident_id", "action", "target"):
            _require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.covered_scope, ActionScope):
            raise TypeError("covered_scope must be an ActionScope")
        if not isinstance(self.status, RollbackStatus):
            raise TypeError("status must be a RollbackStatus")
        _require_aware_datetime(self.declared_at, "declared_at")
        if self.verified_at is not None:
            _require_aware_datetime(self.verified_at, "verified_at")
            if self.verified_at < self.declared_at:
                raise ValueError("verified_at must not precede declared_at")
        if self.status is RollbackStatus.VERIFIED_READY and self.verified_at is None:
            raise ValueError("ready rollback evidence requires verified_at")


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    decision: PolicyDecision
    reason: PolicyReason
    detail: str
    risk: RiskLevel | None = None
    approval_id: str | None = None
    schema_version: str = SAFETY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.decision, PolicyDecision):
            raise TypeError("decision must be a PolicyDecision")
        if not isinstance(self.reason, PolicyReason):
            raise TypeError("reason must be a PolicyReason")
        _require_non_empty(self.detail, "detail")
        if self.risk is not None and not isinstance(self.risk, RiskLevel):
            raise TypeError("risk must be a RiskLevel or None")
        _require_optional_identifier(self.approval_id, "approval_id")
        _require_non_empty(self.schema_version, "schema_version")


@dataclass(frozen=True, slots=True)
class SafetyAuditEvent:
    event_id: str
    request_id: str
    run_id: str
    action: str
    target: str
    decision: PolicyDecision
    reason: PolicyReason
    executor_status: ExecutorStatus
    approval_id: str | None = None
    schema_version: str = SAFETY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "event_id",
            "request_id",
            "run_id",
            "action",
            "target",
            "schema_version",
        ):
            _require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.decision, PolicyDecision):
            raise TypeError("decision must be a PolicyDecision")
        if not isinstance(self.reason, PolicyReason):
            raise TypeError("reason must be a PolicyReason")
        if not isinstance(self.executor_status, ExecutorStatus):
            raise TypeError("executor_status must be an ExecutorStatus")
        _require_optional_identifier(self.approval_id, "approval_id")

    @property
    def executed(self) -> bool:
        return self.executor_status is not ExecutorStatus.NOT_STARTED
