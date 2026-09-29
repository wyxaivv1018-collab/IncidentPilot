"""Typed, dependency-free contracts shared by IncidentPilot components."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

CONTRACT_SCHEMA_VERSION = "1.0"


class StringEnum(str, Enum):
    """A Python 3.10-compatible string enum."""

    def __str__(self) -> str:
        return self.value


class WorkerStatus(StringEnum):
    STOPPED = "stopped"
    RUNNING = "running"


class DatabaseStatus(StringEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class CacheLockStatus(StringEnum):
    """What an environment observer can know about the cache lock."""

    UNKNOWN = "unknown"
    PRESENT = "present"
    CLEARED = "cleared"


class SyncJobStatus(StringEnum):
    FAILED = "failed"
    SUCCESS = "success"


class LogCode(StringEnum):
    SYNC_TIMEOUT = "SYNC_TIMEOUT"
    CACHE_LOCK = "CACHE_LOCK"


class ActionName(StringEnum):
    RESTART_NONCRITICAL_WORKER = "restart_noncritical_worker"
    CLEAR_APPLICATION_CACHE = "clear_application_cache"
    RETRY_SYNC_JOB = "retry_sync_job"


class ActionOutcome(StringEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


class VerificationStatus(StringEnum):
    PASSED = "passed"
    FAILED = "failed"


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class Incident:
    incident_id: str
    scenario_id: str
    title: str
    summary: str
    affected_service: str
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "incident_id",
            "scenario_id",
            "title",
            "summary",
            "affected_service",
            "schema_version",
        ):
            _require_non_empty(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class LogFinding:
    finding_id: str
    incident_id: str
    code: LogCode
    source: str
    message: str
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in ("finding_id", "incident_id", "source", "message", "schema_version"):
            _require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.code, LogCode):
            raise TypeError("code must be a LogCode")


@dataclass(frozen=True, slots=True)
class ActionRequest:
    incident_id: str
    action: ActionName
    target: str
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.incident_id, "incident_id")
        _require_non_empty(self.target, "target")
        _require_non_empty(self.schema_version, "schema_version")
        if not isinstance(self.action, ActionName):
            raise TypeError("action must be an ActionName")


@dataclass(frozen=True, slots=True)
class EnvironmentState:
    incident_id: str
    worker_status: WorkerStatus
    database_status: DatabaseStatus
    cache_lock: CacheLockStatus
    sync_job_status: SyncJobStatus
    visible_logs: tuple[LogFinding, ...]
    executed_actions: tuple[ActionRequest, ...]
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.incident_id, "incident_id")
        _require_non_empty(self.schema_version, "schema_version")
        expected_types = (
            ("worker_status", self.worker_status, WorkerStatus),
            ("database_status", self.database_status, DatabaseStatus),
            ("cache_lock", self.cache_lock, CacheLockStatus),
            ("sync_job_status", self.sync_job_status, SyncJobStatus),
        )
        for field_name, value, expected_type in expected_types:
            if not isinstance(value, expected_type):
                raise TypeError(f"{field_name} must be a {expected_type.__name__}")
        if not isinstance(self.visible_logs, tuple) or not all(
            isinstance(finding, LogFinding) for finding in self.visible_logs
        ):
            raise TypeError("visible_logs must be a tuple of LogFinding values")
        if not isinstance(self.executed_actions, tuple) or not all(
            isinstance(request, ActionRequest) for request in self.executed_actions
        ):
            raise TypeError("executed_actions must be a tuple of ActionRequest values")


@dataclass(frozen=True, slots=True)
class ActionResult:
    request: ActionRequest
    outcome: ActionOutcome
    detail: str
    state: EnvironmentState
    new_findings: tuple[LogFinding, ...] = ()
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.detail, "detail")
        _require_non_empty(self.schema_version, "schema_version")
        if not isinstance(self.request, ActionRequest):
            raise TypeError("request must be an ActionRequest")
        if not isinstance(self.outcome, ActionOutcome):
            raise TypeError("outcome must be an ActionOutcome")
        if not isinstance(self.state, EnvironmentState):
            raise TypeError("state must be an EnvironmentState")
        if not isinstance(self.new_findings, tuple) or not all(
            isinstance(finding, LogFinding) for finding in self.new_findings
        ):
            raise TypeError("new_findings must be a tuple of LogFinding values")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    incident_id: str
    status: VerificationStatus
    detail: str
    state: EnvironmentState
    evidence: tuple[LogFinding, ...]
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.incident_id, "incident_id")
        _require_non_empty(self.detail, "detail")
        _require_non_empty(self.schema_version, "schema_version")
        if not isinstance(self.status, VerificationStatus):
            raise TypeError("status must be a VerificationStatus")
        if not isinstance(self.state, EnvironmentState):
            raise TypeError("state must be an EnvironmentState")
        if not isinstance(self.evidence, tuple) or not all(
            isinstance(finding, LogFinding) for finding in self.evidence
        ):
            raise TypeError("evidence must be a tuple of LogFinding values")
