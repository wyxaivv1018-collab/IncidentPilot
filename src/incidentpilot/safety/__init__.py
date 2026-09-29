"""Programmatic Safety Policy, approval gate, and guarded execution API."""

from incidentpilot.safety.approvals import ApprovalConsumeResult, ApprovalRegistry
from incidentpilot.safety.catalog import (
    ACTION_CATALOG,
    DATABASE_TARGET,
    DELETE_PRODUCTION_DATA,
    MODIFY_PRODUCTION_CONFIG,
    PRODUCTION_CONFIG_TARGET,
    REPAIR_PRODUCTION_DATA,
    RESTART_DATABASE,
)
from incidentpilot.safety.evidence import SafetyEvidenceRegistry
from incidentpilot.safety.guard import (
    AuthorizationBypassError,
    ExecutionGuard,
    ExecutionGuardResult,
    GuardedActionExecutor,
)
from incidentpilot.safety.models import (
    SAFETY_SCHEMA_VERSION,
    ActionArgument,
    ActionScope,
    ActionSpec,
    Approval,
    ApprovalStatus,
    BackupEvidence,
    BackupStatus,
    ExecutorStatus,
    PolicyDecision,
    PolicyEvaluation,
    PolicyReason,
    RiskLevel,
    RollbackEvidence,
    RollbackStatus,
    SafetyActionRequest,
    SafetyAuditEvent,
    SafetyEvidenceReferences,
)
from incidentpilot.safety.policy import SafetyPolicy
from incidentpilot.safety.simulator_adapter import simulator_executors
from incidentpilot.safety.usage import ActionUsageRegistry

__all__ = [
    "ACTION_CATALOG",
    "DATABASE_TARGET",
    "DELETE_PRODUCTION_DATA",
    "MODIFY_PRODUCTION_CONFIG",
    "PRODUCTION_CONFIG_TARGET",
    "REPAIR_PRODUCTION_DATA",
    "RESTART_DATABASE",
    "SAFETY_SCHEMA_VERSION",
    "ActionArgument",
    "ActionScope",
    "ActionSpec",
    "ActionUsageRegistry",
    "Approval",
    "ApprovalConsumeResult",
    "ApprovalRegistry",
    "ApprovalStatus",
    "AuthorizationBypassError",
    "BackupEvidence",
    "BackupStatus",
    "ExecutionGuard",
    "ExecutionGuardResult",
    "ExecutorStatus",
    "GuardedActionExecutor",
    "PolicyDecision",
    "PolicyEvaluation",
    "PolicyReason",
    "RiskLevel",
    "RollbackEvidence",
    "RollbackStatus",
    "SafetyActionRequest",
    "SafetyAuditEvent",
    "SafetyEvidenceReferences",
    "SafetyEvidenceRegistry",
    "SafetyPolicy",
    "simulator_executors",
]
