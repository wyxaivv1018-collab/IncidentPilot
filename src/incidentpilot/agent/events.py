"""Versioned, append-only evidence for one IncidentPilot agent run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Callable, Mapping

from incidentpilot.agent.redaction import redact_json_value, redact_text

AGENT_EVENT_SCHEMA_VERSION = "1.1"


class StringEnum(str, Enum):
    """A Python 3.10-compatible string enum."""

    def __str__(self) -> str:
        return self.value


class AgentEventType(StringEnum):
    RUN_STARTED = "run.started"
    MODEL_TURN_STARTED = "model_turn.started"
    MODEL_TURN_COMPLETED = "model_turn.completed"
    TOOL_REQUESTED = "tool.requested"
    TOOL_RESULT = "tool.result"
    POLICY_DECISION = "policy.decision"
    ACTION_EXECUTED = "action.executed"
    POST_ACTION_VERIFICATION_STARTED = "post_action_verification.started"
    VERIFICATION = "verification.result"
    VERIFICATION_OBSERVATION_DELIVERED = "verification.observation_delivered"
    AGENT_SUMMARY = "agent.summary"
    BUDGET_EXCEEDED = "run.budget_exceeded"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_TIMEOUT = "run.timeout"


_TERMINAL_EVENT_TYPES = frozenset(
    {
        AgentEventType.RUN_COMPLETED,
        AgentEventType.RUN_FAILED,
        AgentEventType.RUN_TIMEOUT,
    }
)


class SummaryKind(StringEnum):
    PLAN = "plan"
    REPLAN = "replan"
    RATIONALE = "rationale"


class TraceInvariantError(RuntimeError):
    """Raised when trace provenance or evidence links are invalid."""


@dataclass(frozen=True, slots=True)
class RunBudget:
    timeout_seconds: float = 240.0
    cancel_grace_seconds: float = 5.0
    max_model_turns: int = 24
    max_tool_calls: int = 32
    max_summary_chars: int = 500

    def __post_init__(self) -> None:
        if not isinstance(self.timeout_seconds, (int, float)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not isinstance(self.cancel_grace_seconds, (int, float)) or self.cancel_grace_seconds < 0:
            raise ValueError("cancel_grace_seconds must be non-negative")
        if not isinstance(self.max_model_turns, int) or self.max_model_turns < 1:
            raise ValueError("max_model_turns must be a positive integer")
        if not isinstance(self.max_tool_calls, int) or self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be a positive integer")
        if not isinstance(self.max_summary_chars, int) or self.max_summary_chars < 1:
            raise ValueError("max_summary_chars must be a positive integer")


@dataclass(frozen=True, slots=True)
class TraceEvent:
    event_id: str
    run_id: str
    sequence: int
    event_type: AgentEventType
    occurred_at: datetime
    summary: str
    payload_json: str
    model_turn_id: str | None = None
    tool_call_id: str | None = None
    related_event_ids: tuple[str, ...] = ()
    schema_version: str = AGENT_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("event_id", "run_id", "summary", "payload_json", "schema_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.sequence, int) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        if not isinstance(self.event_type, AgentEventType):
            raise TypeError("event_type must be an AgentEventType")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.model_turn_id is not None and not self.model_turn_id.strip():
            raise ValueError("model_turn_id must not be blank")
        if self.tool_call_id is not None and not self.tool_call_id.strip():
            raise ValueError("tool_call_id must not be blank")
        if not isinstance(self.related_event_ids, tuple) or not all(
            isinstance(event_id, str) and event_id.strip()
            for event_id in self.related_event_ids
        ):
            raise TypeError("related_event_ids must be a tuple of non-empty strings")
        parsed = json.loads(self.payload_json)
        if not isinstance(parsed, dict):
            raise ValueError("payload_json must encode an object")

    @property
    def payload(self) -> dict[str, object]:
        return json.loads(self.payload_json)


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    run_id: str
    model_turn_id: str
    tool_call_id: str
    tool_name: str
    request_event_id: str


class RunTrace:
    """Thread-safe evidence log with model-turn and tool-call provenance checks."""

    def __init__(
        self,
        run_id: str,
        *,
        max_summary_chars: int = 500,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        if not isinstance(max_summary_chars, int) or max_summary_chars < 1:
            raise ValueError("max_summary_chars must be a positive integer")
        self.run_id = run_id
        self.max_summary_chars = max_summary_chars
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._events: list[TraceEvent] = []
        self._events_by_id: dict[str, TraceEvent] = {}
        self._model_turns: set[str] = set()
        self._tool_invocations: dict[str, ToolInvocation] = {}
        self._tool_results: dict[str, str] = {}
        self._lock = RLock()
        self._model_turn_number = 0
        self._sealed = False

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        with self._lock:
            return tuple(self._events)

    @property
    def model_turn_count(self) -> int:
        with self._lock:
            return self._model_turn_number

    @property
    def tool_call_count(self) -> int:
        with self._lock:
            return len(self._tool_invocations)

    @property
    def sealed(self) -> bool:
        with self._lock:
            return self._sealed

    @property
    def budget_exceeded(self) -> bool:
        return any(event.event_type is AgentEventType.BUDGET_EXCEEDED for event in self.events)

    @property
    def has_passed_verification(self) -> bool:
        return any(
            event.event_type is AgentEventType.VERIFICATION
            and event.payload.get("status") == "passed"
            for event in self.events
        )

    @property
    def latest_verification_passed(self) -> bool:
        latest = next(
            (
                event
                for event in reversed(self.events)
                if event.event_type is AgentEventType.VERIFICATION
            ),
            None,
        )
        return latest is not None and latest.payload.get("status") == "passed"

    def start_run(self) -> TraceEvent:
        return self.emit(
            AgentEventType.RUN_STARTED,
            "Agent run started.",
            {"status": "running"},
        )

    def start_model_turn(self) -> str:
        with self._lock:
            self._require_open()
            self._model_turn_number += 1
            turn_id = f"TURN-{self._model_turn_number:06d}"
            self._model_turns.add(turn_id)
            self._emit_locked(
                AgentEventType.MODEL_TURN_STARTED,
                "Strands model turn started.",
                {"turn_number": self._model_turn_number},
                model_turn_id=turn_id,
            )
            return turn_id

    def complete_model_turn(self, model_turn_id: str, *, status: str) -> TraceEvent:
        with self._lock:
            self._require_model_turn(model_turn_id)
            return self._emit_locked(
                AgentEventType.MODEL_TURN_COMPLETED,
                "Strands model turn completed.",
                {"status": status},
                model_turn_id=model_turn_id,
            )

    def record_tool_request(
        self,
        model_turn_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> ToolInvocation:
        with self._lock:
            self._require_model_turn(model_turn_id)
            for name, value in (("tool_call_id", tool_call_id), ("tool_name", tool_name)):
                if not isinstance(value, str) or not value.strip():
                    raise TraceInvariantError(f"{name} must be a non-empty string")
            if tool_call_id in self._tool_invocations:
                raise TraceInvariantError(f"duplicate tool_call_id: {tool_call_id}")
            event = self._emit_locked(
                AgentEventType.TOOL_REQUESTED,
                f"Model requested tool {tool_name}.",
                {"tool_name": tool_name, "arguments": dict(arguments)},
                model_turn_id=model_turn_id,
                tool_call_id=tool_call_id,
            )
            invocation = ToolInvocation(
                run_id=self.run_id,
                model_turn_id=model_turn_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                request_event_id=event.event_id,
            )
            self._tool_invocations[tool_call_id] = invocation
            return invocation

    def resolve_tool_invocation(self, tool_call_id: str) -> ToolInvocation:
        with self._lock:
            invocation = self._tool_invocations.get(tool_call_id)
            if invocation is None:
                raise TraceInvariantError(
                    "tool execution has no originating Strands model-turn request"
                )
            return invocation

    def record_tool_result(
        self,
        invocation: ToolInvocation,
        *,
        status: str,
        summary: str,
        payload: Mapping[str, object],
        related_event_ids: tuple[str, ...] = (),
    ) -> TraceEvent:
        with self._lock:
            self._require_invocation(invocation)
            if invocation.tool_call_id in self._tool_results:
                raise TraceInvariantError(
                    f"tool call already has a result: {invocation.tool_call_id}"
                )
            event = self._emit_locked(
                AgentEventType.TOOL_RESULT,
                summary,
                {"status": status, **dict(payload)},
                model_turn_id=invocation.model_turn_id,
                tool_call_id=invocation.tool_call_id,
                related_event_ids=(invocation.request_event_id, *related_event_ids),
            )
            self._tool_results[invocation.tool_call_id] = event.event_id
            return event

    def has_tool_result(self, tool_call_id: str) -> bool:
        with self._lock:
            return tool_call_id in self._tool_results

    def record_policy_decision(
        self,
        invocation: ToolInvocation,
        payload: Mapping[str, object],
    ) -> TraceEvent:
        with self._lock:
            self._require_invocation(invocation)
            return self._emit_locked(
                AgentEventType.POLICY_DECISION,
                "Programmatic safety policy evaluated the requested action.",
                payload,
                model_turn_id=invocation.model_turn_id,
                tool_call_id=invocation.tool_call_id,
                related_event_ids=(invocation.request_event_id,),
            )

    def record_action_executed(
        self,
        invocation: ToolInvocation,
        payload: Mapping[str, object],
        *,
        related_event_ids: tuple[str, ...] = (),
    ) -> TraceEvent:
        with self._lock:
            self._require_invocation(invocation)
            return self._emit_locked(
                AgentEventType.ACTION_EXECUTED,
                "The guarded action executor returned after an authorized mutation request.",
                payload,
                model_turn_id=invocation.model_turn_id,
                tool_call_id=invocation.tool_call_id,
                related_event_ids=(invocation.request_event_id, *related_event_ids),
            )

    def record_post_action_verification_started(
        self,
        invocation: ToolInvocation,
        *,
        action_event_id: str,
    ) -> TraceEvent:
        with self._lock:
            self._require_invocation(invocation)
            return self._emit_locked(
                AgentEventType.POST_ACTION_VERIFICATION_STARTED,
                "The runtime started authoritative verification before returning the action.",
                {
                    "verification_trigger": "post_action_barrier",
                    "verified_action_event_id": action_event_id,
                },
                model_turn_id=invocation.model_turn_id,
                tool_call_id=invocation.tool_call_id,
                related_event_ids=(action_event_id,),
            )

    def record_verification(
        self,
        invocation: ToolInvocation,
        payload: Mapping[str, object],
        *,
        related_event_ids: tuple[str, ...] = (),
    ) -> TraceEvent:
        with self._lock:
            self._require_invocation(invocation)
            return self._emit_locked(
                AgentEventType.VERIFICATION,
                "The environment returned an authoritative verification result.",
                payload,
                model_turn_id=invocation.model_turn_id,
                tool_call_id=invocation.tool_call_id,
                related_event_ids=(invocation.request_event_id, *related_event_ids),
            )

    def record_verification_observation_delivered(
        self,
        invocation: ToolInvocation,
        *,
        action_event_id: str,
        verification_event_id: str,
        status: str,
    ) -> TraceEvent:
        with self._lock:
            self._require_invocation(invocation)
            return self._emit_locked(
                AgentEventType.VERIFICATION_OBSERVATION_DELIVERED,
                "The runtime attached the authoritative observation to the action response.",
                {
                    "status": status,
                    "delivery_channel": "action_tool_result",
                    "verification_trigger": "post_action_barrier",
                    "verified_action_event_id": action_event_id,
                    "verification_event_id": verification_event_id,
                },
                model_turn_id=invocation.model_turn_id,
                tool_call_id=invocation.tool_call_id,
                related_event_ids=(action_event_id, verification_event_id),
            )

    def record_agent_summary(
        self,
        invocation: ToolInvocation,
        *,
        kind: SummaryKind,
        summary: str,
        evidence_event_ids: tuple[str, ...],
    ) -> TraceEvent:
        if not isinstance(kind, SummaryKind):
            raise TypeError("kind must be a SummaryKind")
        if not isinstance(summary, str) or not summary.strip():
            raise TraceInvariantError("summary must be a non-empty string")
        if len(summary) > self.max_summary_chars:
            raise TraceInvariantError("summary exceeds the configured character budget")
        with self._lock:
            self._require_invocation(invocation)
            prior_observations = tuple(
                event
                for event in self._events
                if event.event_type in (AgentEventType.TOOL_RESULT, AgentEventType.VERIFICATION)
            )
            if not evidence_event_ids and (kind is not SummaryKind.PLAN or prior_observations):
                raise TraceInvariantError(
                    "only the initial plan may omit prior observable evidence"
                )
            if len(set(evidence_event_ids)) != len(evidence_event_ids):
                raise TraceInvariantError("evidence_event_ids must be unique")
            for event_id in evidence_event_ids:
                evidence = self._events_by_id.get(event_id)
                if evidence is None:
                    raise TraceInvariantError(f"unknown evidence event: {event_id}")
                if evidence.event_type not in (
                    AgentEventType.TOOL_RESULT,
                    AgentEventType.VERIFICATION,
                ):
                    raise TraceInvariantError(
                        f"event is not observable tool evidence: {event_id}"
                    )
                if evidence.event_type is AgentEventType.TOOL_RESULT:
                    evidence_invocation = self._tool_invocations.get(evidence.tool_call_id or "")
                    if (
                        evidence_invocation is not None
                        and evidence_invocation.tool_name == "record_decision_summary"
                    ):
                        raise TraceInvariantError(
                            "summary acknowledgements are not substantive evidence"
                        )
            return self._emit_locked(
                AgentEventType.AGENT_SUMMARY,
                summary.strip(),
                {"kind": kind.value, "evidence_event_ids": evidence_event_ids},
                model_turn_id=invocation.model_turn_id,
                tool_call_id=invocation.tool_call_id,
                related_event_ids=(invocation.request_event_id, *evidence_event_ids),
            )

    def record_budget_exceeded(self, budget_name: str, limit: int) -> TraceEvent:
        return self.emit(
            AgentEventType.BUDGET_EXCEEDED,
            "The bounded agent run reached a configured budget.",
            {"budget": budget_name, "limit": limit},
        )

    def emit(
        self,
        event_type: AgentEventType,
        summary: str,
        payload: Mapping[str, object],
        *,
        model_turn_id: str | None = None,
        tool_call_id: str | None = None,
        related_event_ids: tuple[str, ...] = (),
    ) -> TraceEvent:
        with self._lock:
            return self._emit_locked(
                event_type,
                summary,
                payload,
                model_turn_id=model_turn_id,
                tool_call_id=tool_call_id,
                related_event_ids=related_event_ids,
            )

    def _emit_locked(
        self,
        event_type: AgentEventType,
        summary: str,
        payload: Mapping[str, object],
        *,
        model_turn_id: str | None = None,
        tool_call_id: str | None = None,
        related_event_ids: tuple[str, ...] = (),
    ) -> TraceEvent:
        if not isinstance(event_type, AgentEventType):
            raise TypeError("event_type must be an AgentEventType")
        self._require_open()
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary must be a non-empty string")
        for related_event_id in related_event_ids:
            if related_event_id not in self._events_by_id:
                raise TraceInvariantError(f"unknown related event: {related_event_id}")
        occurred_at = self._clock()
        if not isinstance(occurred_at, datetime):
            raise TypeError("trace clock must return datetime")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("trace clock must return a timezone-aware datetime")
        redacted_payload = redact_json_value(payload)
        payload_json = json.dumps(
            redacted_payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        parsed_payload = json.loads(payload_json)
        if not isinstance(parsed_payload, dict):
            raise TypeError("event payload must be JSON object compatible")
        sequence = len(self._events) + 1
        event = TraceEvent(
            event_id=f"EVT-{sequence:06d}",
            run_id=self.run_id,
            sequence=sequence,
            event_type=event_type,
            occurred_at=occurred_at,
            summary=redact_text(summary.strip()),
            payload_json=payload_json,
            model_turn_id=model_turn_id,
            tool_call_id=tool_call_id,
            related_event_ids=related_event_ids,
        )
        self._events.append(event)
        self._events_by_id[event.event_id] = event
        if event_type in _TERMINAL_EVENT_TYPES:
            self._sealed = True
        return event

    def _require_open(self) -> None:
        if self._sealed:
            raise TraceInvariantError("trace is sealed by its terminal event")

    def _require_model_turn(self, model_turn_id: str) -> None:
        if model_turn_id not in self._model_turns:
            raise TraceInvariantError(f"unknown model turn: {model_turn_id}")

    def _require_invocation(self, invocation: ToolInvocation) -> None:
        if not isinstance(invocation, ToolInvocation):
            raise TypeError("invocation must be a ToolInvocation")
        canonical = self._tool_invocations.get(invocation.tool_call_id)
        if canonical != invocation:
            raise TraceInvariantError("tool invocation does not match recorded provenance")
