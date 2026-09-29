"""Stable, dependency-free contracts for the C08 demo API."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from incidentpilot.agent.controller import AgentRunStatus
from incidentpilot.agent.events import TraceEvent

API_SCHEMA_VERSION = "1.0"
DEMO_SCENARIO_ID = "order-sync-double-fault"


class StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class RunState(StringEnum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    AUTH_BLOCKED = "AUTH_BLOCKED"
    RUNTIME_BLOCKED = "RUNTIME_BLOCKED"


ACTIVE_RUN_STATES = frozenset(
    {RunState.STARTING, RunState.RUNNING, RunState.CANCEL_REQUESTED}
)
TERMINAL_RUN_STATES = frozenset(set(RunState) - set(ACTIVE_RUN_STATES))


class ApiErrorCode(StringEnum):
    UNTRUSTED_REQUEST = "UNTRUSTED_REQUEST"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    INVALID_JSON = "INVALID_JSON"
    INVALID_REQUEST = "INVALID_REQUEST"
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
    SCENARIO_NOT_SUPPORTED = "SCENARIO_NOT_SUPPORTED"
    ACTIVE_RUN_EXISTS = "ACTIVE_RUN_EXISTS"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    RUN_NOT_ACTIVE = "RUN_NOT_ACTIVE"
    INVALID_EVENT_CURSOR = "INVALID_EVENT_CURSOR"
    APPROVAL_REQUEST_NOT_FOUND = "APPROVAL_REQUEST_NOT_FOUND"
    APPROVAL_BINDING_MISMATCH = "APPROVAL_BINDING_MISMATCH"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_ALREADY_USED = "APPROVAL_ALREADY_USED"
    APPROVAL_NOT_AVAILABLE = "APPROVAL_NOT_AVAILABLE"
    ARTIFACT_NOT_READY = "ARTIFACT_NOT_READY"
    ARTIFACT_INVALID = "ARTIFACT_INVALID"
    ARTIFACT_GENERATION_FAILED = "ARTIFACT_GENERATION_FAILED"
    RESOLUTION_PROOF_INVALID = "RESOLUTION_PROOF_INVALID"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    ROUTE_NOT_FOUND = "ROUTE_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiError(RuntimeError):
    """A stable public error without internal exception or credential text."""

    def __init__(
        self,
        *,
        status_code: int,
        code: ApiErrorCode,
        message: str,
        retryable: bool = False,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, object]:
        error: dict[str, object] = {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            error["details"] = dict(self.details)
        return {"schema_version": API_SCHEMA_VERSION, "error": error}


@dataclass(frozen=True, slots=True)
class DemoRunCompletion:
    status: AgentRunStatus
    detail: str
    final_text: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, AgentRunStatus):
            raise TypeError("status must be an AgentRunStatus")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise ValueError("detail must be a non-empty string")
        if self.final_text is not None and not isinstance(self.final_text, str):
            raise TypeError("final_text must be a string or None")


def serialize_trace_event(event: TraceEvent) -> dict[str, object]:
    if not isinstance(event, TraceEvent):
        raise TypeError("event must be a TraceEvent")
    return {
        "event_id": event.event_id,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "event_type": event.event_type.value,
        "occurred_at": event.occurred_at.isoformat(),
        "summary": event.summary,
        "payload": event.payload,
        "model_turn_id": event.model_turn_id,
        "tool_call_id": event.tool_call_id,
        "related_event_ids": list(event.related_event_ids),
        "schema_version": event.schema_version,
    }


def run_state_from_agent(status: AgentRunStatus) -> RunState:
    try:
        return RunState(status.value)
    except ValueError as exc:
        raise ValueError(f"unsupported Agent run status: {status.value}") from exc
