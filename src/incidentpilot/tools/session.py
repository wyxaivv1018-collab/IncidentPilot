"""Per-run typed tool session with trace evidence and guarded mutations."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from threading import Condition, Event, Lock
from typing import Callable, TypeVar

from incidentpilot.agent.events import RunTrace, SummaryKind, ToolInvocation, TraceInvariantError
from incidentpilot.contracts import ActionName, ActionResult, VerificationStatus
from incidentpilot.memory.read_tools import KnowledgeReads
from incidentpilot.safety import ActionArgument, ExecutionGuardResult
from incidentpilot.tools.adapters import GuardedActionAdapter, SimulatorReadAdapter
from incidentpilot.tools.serialization import InvalidToolResult, to_json_value


_TerminalResult = TypeVar("_TerminalResult")


class ToolResponseStatus(str, Enum):
    COMPLETED = "completed"
    DENIED = "denied"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ToolResponse:
    status: ToolResponseStatus
    result_event_id: str
    data: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "result_event_id": self.result_event_id,
            "data": dict(self.data),
        }


class IncidentToolSession:
    """All model-visible tools for one run; this object never chooses the next tool."""

    def __init__(
        self,
        *,
        run_id: str,
        trace: RunTrace,
        reads: SimulatorReadAdapter,
        actions: GuardedActionAdapter,
        knowledge: KnowledgeReads | None = None,
    ) -> None:
        if run_id != trace.run_id:
            raise ValueError("tool session run_id must match trace")
        if not isinstance(reads, SimulatorReadAdapter):
            raise TypeError("reads must be a SimulatorReadAdapter")
        if not isinstance(actions, GuardedActionAdapter):
            raise TypeError("actions must be a GuardedActionAdapter")
        self.run_id = run_id
        self.trace = trace
        self._reads = reads
        self._knowledge = knowledge or KnowledgeReads()
        self._actions = actions
        self._request_number = 0
        self._request_lock = Lock()
        self._lifecycle_lock = Lock()
        self._lifecycle_condition = Condition(self._lifecycle_lock)
        self._in_flight_actions = 0
        self._action_admission_closed = False
        self._terminal_committed = False
        self._pending_verification_action_result_id: str | None = None
        self._pending_verification_action_model_turn_id: str | None = None
        self._last_verification_result_event_id: str | None = None
        self._last_verification_model_turn_id: str | None = None
        self._cancelled = Event()

    def cancel(self) -> None:
        """Prevent any new backend read or guarded action after the run is stopped."""
        with self._lifecycle_condition:
            if self._terminal_committed:
                return
            self._action_admission_closed = True
            self._cancelled.set()
            self._lifecycle_condition.notify_all()

    def close_action_admission(self) -> None:
        """Prevent any action that has not already crossed the lifecycle boundary."""
        with self._lifecycle_condition:
            self._action_admission_closed = True
            self._lifecycle_condition.notify_all()

    def close_action_admission_and_wait_for_quiescence(
        self,
    ) -> bool:
        """Close action admission, wait for evidence, and report external cancellation."""
        with self._lifecycle_condition:
            self._action_admission_closed = True
            self._lifecycle_condition.notify_all()
            while self._in_flight_actions:
                self._lifecycle_condition.wait()
            return self._cancelled.is_set()

    def commit_terminal(
        self,
        commit: Callable[[bool], _TerminalResult],
    ) -> _TerminalResult:
        """Commit after quiescence under the same boundary as direct Session cancel."""
        with self._lifecycle_condition:
            self._action_admission_closed = True
            self._lifecycle_condition.notify_all()
            while self._in_flight_actions:
                self._lifecycle_condition.wait()
            self._terminal_committed = True
            return commit(self._cancelled.is_set())

    def wait_for_quiescence(self, *, timeout_seconds: float | None = None) -> bool:
        """Wait until every action admitted before cancellation has finished its evidence."""
        if timeout_seconds is not None and (
            not isinstance(timeout_seconds, (int, float)) or timeout_seconds < 0
        ):
            raise ValueError("timeout_seconds must be non-negative or None")
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        with self._lifecycle_condition:
            while self._in_flight_actions:
                wait_for = None
                if deadline is not None:
                    wait_for = deadline - time.monotonic()
                    if wait_for <= 0:
                        return False
                self._lifecycle_condition.wait(wait_for)
            return True

    @property
    def has_pending_authoritative_verification(self) -> bool:
        with self._lifecycle_condition:
            return self._pending_verification_action_result_id is not None

    def read_incident(self, invocation: ToolInvocation) -> ToolResponse:
        self._validate_invocation(invocation, "read_incident")
        try:
            incident = self._reads.read_incident()
            serialized = to_json_value(incident)
            if not isinstance(serialized, dict):
                raise InvalidToolResult("incident must serialize to an object")
            observable = {
                key: serialized[key]
                for key in (
                    "incident_id",
                    "title",
                    "summary",
                    "affected_service",
                    "schema_version",
                )
            }
        except (InvalidToolResult, KeyError, TypeError, ValueError):
            return self._tool_error(invocation, "The incident tool returned invalid data.")
        except Exception:
            return self._tool_error(invocation, "The incident backend failed safely.")
        result = self.trace.record_tool_result(
            invocation,
            status=ToolResponseStatus.COMPLETED.value,
            summary="The incident tool returned current user-visible incident data.",
            payload={"data": observable},
        )
        return ToolResponse(
            ToolResponseStatus.COMPLETED,
            result.event_id,
            {"incident": observable},
        )

    def read_logs(self, invocation: ToolInvocation) -> ToolResponse:
        return self._read_tool(
            invocation,
            expected_name="read_logs",
            operation=self._reads.read_logs,
            label="logs",
        )

    def read_environment(self, invocation: ToolInvocation) -> ToolResponse:
        return self._read_tool(
            invocation,
            expected_name="read_environment",
            operation=self._reads.read_environment,
            label="environment",
        )

    def lookup_historical_memory(
        self, invocation: ToolInvocation, *, query: str, limit: int = 5,
    ) -> ToolResponse:
        return self._read_tool(
            invocation, expected_name="lookup_historical_memory",
            operation=lambda: self._knowledge.memory(query, limit, exclude_run_id=self.run_id),
            label="historical_memory", knowledge=True,
        )

    def lookup_sop(
        self, invocation: ToolInvocation, *, query: str, limit: int = 5,
    ) -> ToolResponse:
        return self._read_tool(
            invocation, expected_name="lookup_sop",
            operation=lambda: self._knowledge.sop(query, limit),
            label="sop", knowledge=True,
        )

    def verify_recovery(self, invocation: ToolInvocation) -> ToolResponse:
        self._validate_invocation(invocation, "verify_recovery")
        with self._lifecycle_condition:
            if self._pending_verification_action_result_id is not None:
                return self._verification_required_response(
                    invocation,
                    self._pending_verification_action_result_id,
                )
            try:
                verification = self._reads.verify_recovery()
                serialized = to_json_value(verification)
                if not isinstance(serialized, dict):
                    raise InvalidToolResult("verification must serialize to an object")
                verification_event = self.trace.record_verification(
                    invocation,
                    {
                        "status": verification.status.value,
                        "verification": serialized,
                        "verification_trigger": "on_demand",
                        "verified_action_event_id": None,
                    },
                )
                result = self.trace.record_tool_result(
                    invocation,
                    status=ToolResponseStatus.COMPLETED.value,
                    summary="Verification tool returned the current environment result.",
                    payload={
                        "verification_event_id": verification_event.event_id,
                        "status": verification.status.value,
                        "data": serialized,
                        "verification_trigger": "on_demand",
                        "verified_action_event_id": None,
                    },
                    related_event_ids=(verification_event.event_id,),
                )
                self._last_verification_result_event_id = verification_event.event_id
                self._last_verification_model_turn_id = invocation.model_turn_id
                return ToolResponse(
                    ToolResponseStatus.COMPLETED,
                    result.event_id,
                    {
                        "verification_event_id": verification_event.event_id,
                        "verification_status": verification.status.value,
                        "incident_resolved": verification.status is VerificationStatus.PASSED,
                        "verification_trigger": "on_demand",
                        "verified_action_event_id": None,
                        "verification": serialized,
                    },
                )
            except (InvalidToolResult, TypeError, ValueError):
                return self._tool_error(invocation, "Verification returned invalid data.")
            except Exception:
                return self._tool_error(invocation, "Verification backend failed safely.")

    def restart_noncritical_worker(
        self,
        invocation: ToolInvocation,
        *,
        target: str,
    ) -> ToolResponse:
        self._validate_invocation(invocation, ActionName.RESTART_NONCRITICAL_WORKER.value)
        return self.execute_requested_action(
            invocation,
            action=ActionName.RESTART_NONCRITICAL_WORKER.value,
            target=target,
        )

    def clear_application_cache(
        self,
        invocation: ToolInvocation,
        *,
        target: str,
        max_keys: int,
    ) -> ToolResponse:
        self._validate_invocation(invocation, ActionName.CLEAR_APPLICATION_CACHE.value)
        if isinstance(max_keys, bool) or not isinstance(max_keys, int):
            return self._tool_error(invocation, "max_keys must be an integer.")
        return self.execute_requested_action(
            invocation,
            action=ActionName.CLEAR_APPLICATION_CACHE.value,
            target=target,
            arguments=(ActionArgument("max_keys", str(max_keys)),),
        )

    def retry_sync_job(
        self,
        invocation: ToolInvocation,
        *,
        target: str,
    ) -> ToolResponse:
        self._validate_invocation(invocation, ActionName.RETRY_SYNC_JOB.value)
        return self.execute_requested_action(
            invocation,
            action=ActionName.RETRY_SYNC_JOB.value,
            target=target,
        )

    def execute_requested_action(
        self,
        invocation: ToolInvocation,
        *,
        action: str,
        target: str,
        arguments: tuple[ActionArgument, ...] = (),
        approval_id: str | None = None,
    ) -> ToolResponse:
        self._validate_invocation(invocation, action)
        with self._lifecycle_condition:
            while self._in_flight_actions:
                self._lifecycle_condition.wait()
                self._require_action_admission_open()
            self._require_action_admission_open()
            if self._pending_verification_action_result_id is not None:
                return self._verification_required_response(
                    invocation,
                    self._pending_verification_action_result_id,
                )
            if self._last_verification_model_turn_id == invocation.model_turn_id:
                return self._observation_roundtrip_required_response(
                    invocation,
                    reason="VERIFICATION_OBSERVATION_NOT_YET_RETURNED",
                    related_event_id=self._last_verification_result_event_id,
                )
            self._last_verification_result_event_id = None
            self._last_verification_model_turn_id = None
            request_id = self._next_request_id()
            self._in_flight_actions += 1
        try:
            try:
                guarded = self._actions.execute(
                    request_id=request_id,
                    run_id=self.run_id,
                    action=action,
                    target=target,
                    arguments=arguments,
                    approval_id=approval_id,
                )
            except (TypeError, ValueError):
                return self._tool_error(invocation, "Action request was invalid before execution.")
            except Exception:
                return self._tool_error(invocation, "Guarded action handler failed safely.")
            return self._action_response(invocation, guarded)
        finally:
            with self._lifecycle_condition:
                self._in_flight_actions -= 1
                self._lifecycle_condition.notify_all()

    def record_decision_summary(
        self,
        invocation: ToolInvocation,
        *,
        kind: str,
        summary: str,
        evidence_event_ids: tuple[str, ...],
    ) -> ToolResponse:
        self._validate_invocation(invocation, "record_decision_summary")
        try:
            summary_kind = SummaryKind(kind)
        except (TypeError, ValueError):
            return self._tool_error(
                invocation,
                "Summary kind must be one of: plan, replan, rationale.",
            )
        if isinstance(summary, str) and len(summary) > self.trace.max_summary_chars:
            return self._tool_error(
                invocation,
                f"Summary exceeds the configured character budget: received {len(summary)} "
                f"characters; maximum {self.trace.max_summary_chars}. Summary was not recorded.",
            )
        try:
            summary_event = self.trace.record_agent_summary(
                invocation,
                kind=summary_kind,
                summary=summary,
                evidence_event_ids=evidence_event_ids,
            )
            result = self.trace.record_tool_result(
                invocation,
                status=ToolResponseStatus.COMPLETED.value,
                summary="The concise Agent summary and its evidence links were recorded.",
                payload={
                    "summary_event_id": summary_event.event_id,
                    "kind": summary_kind.value,
                },
                related_event_ids=(summary_event.event_id,),
            )
            return ToolResponse(
                ToolResponseStatus.COMPLETED,
                result.event_id,
                {"summary_event_id": summary_event.event_id},
            )
        except (TraceInvariantError, TypeError, ValueError):
            return self._tool_error(
                invocation,
                "Summary or evidence references were invalid and were not recorded.",
            )

    def _read_tool(
        self,
        invocation: ToolInvocation,
        *,
        expected_name: str,
        operation: Callable[[], object],
        label: str,
        knowledge: bool = False,
    ) -> ToolResponse:
        self._validate_invocation(invocation, expected_name)
        try:
            serialized = to_json_value(operation())
        except (InvalidToolResult, TypeError, ValueError):
            return self._tool_error(invocation, f"The {label} tool returned invalid data.")
        except Exception:
            return self._tool_error(invocation, f"The {label} backend failed safely.")
        result = self.trace.record_tool_result(
            invocation,
            status=ToolResponseStatus.COMPLETED.value,
            summary=(f"The {label} tool returned advisory knowledge, not current incident facts."
                     if knowledge else f"The {label} tool returned current observable data."),
            payload={"data": serialized},
        )
        return ToolResponse(
            ToolResponseStatus.COMPLETED,
            result.event_id,
            {label: serialized},
        )

    def _action_response(
        self,
        invocation: ToolInvocation,
        guarded: ExecutionGuardResult,
    ) -> ToolResponse:
        evaluation = guarded.evaluation
        policy_event = self.trace.record_policy_decision(
            invocation,
            {
                "decision": evaluation.decision.value,
                "reason": evaluation.reason.value,
                "risk": evaluation.risk.value if evaluation.risk is not None else None,
                "executed": guarded.executed,
                "executor_status": guarded.audit_event.executor_status.value,
                "safety_event_id": guarded.audit_event.event_id,
            },
        )
        if not guarded.executed:
            result = self.trace.record_tool_result(
                invocation,
                status=ToolResponseStatus.DENIED.value,
                summary="The programmatic safety layer did not execute the requested action.",
                payload={
                    "policy_event_id": policy_event.event_id,
                    "decision": evaluation.decision.value,
                    "reason": evaluation.reason.value,
                    "executed": False,
                },
                related_event_ids=(policy_event.event_id,),
            )
            return ToolResponse(
                ToolResponseStatus.DENIED,
                result.event_id,
                {
                    "policy_event_id": policy_event.event_id,
                    "decision": evaluation.decision.value,
                    "reason": evaluation.reason.value,
                    "executed": False,
                },
            )
        action_result_valid = isinstance(guarded.executor_result, ActionResult)
        serialized_action: dict[str, object] | None = None
        if action_result_valid:
            try:
                candidate = to_json_value(guarded.executor_result)
                if isinstance(candidate, dict):
                    serialized_action = candidate
                else:
                    action_result_valid = False
            except (InvalidToolResult, TypeError, ValueError):
                action_result_valid = False
        operation_outcome = (
            guarded.executor_result.outcome.value
            if action_result_valid and isinstance(guarded.executor_result, ActionResult)
            else None
        )
        action_event = self.trace.record_action_executed(
            invocation,
            {
                "policy_event_id": policy_event.event_id,
                "executed": True,
                "executor_status": guarded.audit_event.executor_status.value,
                "operation_outcome": operation_outcome,
                "action_result_valid": action_result_valid,
                "action_result": serialized_action,
                "incident_resolved": False,
            },
            related_event_ids=(policy_event.event_id,),
        )
        with self._lifecycle_condition:
            self._pending_verification_action_result_id = action_event.event_id
            self._pending_verification_action_model_turn_id = invocation.model_turn_id
        started_event = self.trace.record_post_action_verification_started(
            invocation,
            action_event_id=action_event.event_id,
        )
        try:
            verification = self._reads.verify_recovery()
            serialized_verification = to_json_value(verification)
            if not isinstance(serialized_verification, dict):
                raise InvalidToolResult("verification must serialize to an object")
        except (InvalidToolResult, TypeError, ValueError):
            return self._post_action_verification_error(
                invocation,
                policy_event_id=policy_event.event_id,
                action_event_id=action_event.event_id,
                started_event_id=started_event.event_id,
                operation_outcome=operation_outcome,
                serialized_action=serialized_action,
                detail="Post-action verification returned invalid data.",
            )
        except Exception:
            return self._post_action_verification_error(
                invocation,
                policy_event_id=policy_event.event_id,
                action_event_id=action_event.event_id,
                started_event_id=started_event.event_id,
                operation_outcome=operation_outcome,
                serialized_action=serialized_action,
                detail="Post-action verification backend failed safely.",
            )
        verification_event = self.trace.record_verification(
            invocation,
            {
                "status": verification.status.value,
                "verification": serialized_verification,
                "verification_trigger": "post_action_barrier",
                "verified_action_event_id": action_event.event_id,
                "barrier_started_event_id": started_event.event_id,
            },
            related_event_ids=(action_event.event_id, started_event.event_id),
        )
        observation_event = self.trace.record_verification_observation_delivered(
            invocation,
            action_event_id=action_event.event_id,
            verification_event_id=verification_event.event_id,
            status=verification.status.value,
        )
        verification_data = {
            "barrier_started_event_id": started_event.event_id,
            "verification_event_id": verification_event.event_id,
            "observation_event_id": observation_event.event_id,
            "verification_status": verification.status.value,
            "incident_resolved": verification.status is VerificationStatus.PASSED,
            "verification_trigger": "post_action_barrier",
            "verified_action_event_id": action_event.event_id,
            "verification": serialized_verification,
        }
        response_status = (
            ToolResponseStatus.COMPLETED if action_result_valid else ToolResponseStatus.ERROR
        )
        response_data = {
            "policy_event_id": policy_event.event_id,
            "action_event_id": action_event.event_id,
            "executed": True,
            "operation_outcome": operation_outcome,
            "action_result_establishes_resolution": False,
            "action_result": serialized_action,
            "post_action_verification": verification_data,
        }
        if not action_result_valid:
            response_data["error"] = "Guarded executor returned invalid action data."
        result = self.trace.record_tool_result(
            invocation,
            status=response_status.value,
            summary=(
                "The action outcome and mandatory authoritative verification were returned "
                "as separate observations."
                if action_result_valid
                else "The action adapter result was invalid; authoritative verification still ran."
            ),
            payload=response_data,
            related_event_ids=(
                policy_event.event_id,
                action_event.event_id,
                started_event.event_id,
                verification_event.event_id,
                observation_event.event_id,
            ),
        )
        with self._lifecycle_condition:
            self._pending_verification_action_result_id = None
            self._pending_verification_action_model_turn_id = None
            self._last_verification_result_event_id = verification_event.event_id
            self._last_verification_model_turn_id = invocation.model_turn_id
        return ToolResponse(response_status, result.event_id, response_data)

    def _post_action_verification_error(
        self,
        invocation: ToolInvocation,
        *,
        policy_event_id: str,
        action_event_id: str,
        started_event_id: str,
        operation_outcome: str | None,
        serialized_action: dict[str, object] | None,
        detail: str,
    ) -> ToolResponse:
        data = {
            "policy_event_id": policy_event_id,
            "action_event_id": action_event_id,
            "executed": True,
            "operation_outcome": operation_outcome,
            "action_result_establishes_resolution": False,
            "action_result": serialized_action,
            "post_action_verification": {
                "barrier_started_event_id": started_event_id,
                "verification_status": "error",
                "incident_resolved": False,
                "verification_trigger": "post_action_barrier",
                "verified_action_event_id": action_event_id,
                "error": detail,
            },
        }
        result = self.trace.record_tool_result(
            invocation,
            status=ToolResponseStatus.ERROR.value,
            summary=detail,
            payload=data,
            related_event_ids=(policy_event_id, action_event_id, started_event_id),
        )
        return ToolResponse(ToolResponseStatus.ERROR, result.event_id, data)

    def _verification_required_response(
        self,
        invocation: ToolInvocation,
        pending_action_result_event_id: str,
    ) -> ToolResponse:
        result = self.trace.record_tool_result(
            invocation,
            status=ToolResponseStatus.DENIED.value,
            summary=(
                "The runtime lifecycle blocked another mutation until authoritative "
                "verification observes the current recovery state."
            ),
            payload={
                "reason": "AUTHORITATIVE_VERIFICATION_REQUIRED",
                "executed": False,
                "pending_action_result_event_id": pending_action_result_event_id,
            },
            related_event_ids=(pending_action_result_event_id,),
        )
        return ToolResponse(
            ToolResponseStatus.DENIED,
            result.event_id,
            {
                "reason": "AUTHORITATIVE_VERIFICATION_REQUIRED",
                "executed": False,
                "pending_action_result_event_id": pending_action_result_event_id,
            },
        )

    def _observation_roundtrip_required_response(
        self,
        invocation: ToolInvocation,
        *,
        reason: str,
        related_event_id: str | None,
    ) -> ToolResponse:
        related_event_ids = (related_event_id,) if related_event_id is not None else ()
        result = self.trace.record_tool_result(
            invocation,
            status=ToolResponseStatus.DENIED.value,
            summary=(
                "The runtime lifecycle requires the latest observation to return to a later "
                "model turn before this operation can execute."
            ),
            payload={
                "reason": reason,
                "executed": False,
                "related_observation_event_id": related_event_id,
            },
            related_event_ids=related_event_ids,
        )
        return ToolResponse(
            ToolResponseStatus.DENIED,
            result.event_id,
            {
                "reason": reason,
                "executed": False,
                "related_observation_event_id": related_event_id,
            },
        )

    def _tool_error(
        self,
        invocation: ToolInvocation,
        detail: str,
        *,
        related_event_ids: tuple[str, ...] = (),
    ) -> ToolResponse:
        if self.trace.has_tool_result(invocation.tool_call_id):
            raise TraceInvariantError("cannot record a second tool error result")
        result = self.trace.record_tool_result(
            invocation,
            status=ToolResponseStatus.ERROR.value,
            summary=detail,
            payload={"error": detail},
            related_event_ids=related_event_ids,
        )
        return ToolResponse(
            ToolResponseStatus.ERROR,
            result.event_id,
            {"error": detail},
        )

    def _validate_invocation(self, invocation: ToolInvocation, expected_name: str) -> None:
        if self._cancelled.is_set():
            raise TraceInvariantError("tool session is cancelled")
        canonical = self.trace.resolve_tool_invocation(invocation.tool_call_id)
        if canonical != invocation:
            raise TraceInvariantError("tool invocation provenance does not match the trace")
        if invocation.run_id != self.run_id:
            raise TraceInvariantError("tool invocation belongs to another run")
        if invocation.tool_name != expected_name:
            raise TraceInvariantError("tool invocation name does not match the adapter")

    def _require_action_admission_open(self) -> None:
        if not self._action_admission_closed:
            return
        if self._cancelled.is_set():
            raise TraceInvariantError("tool session is cancelled")
        raise TraceInvariantError("tool session is closed for terminalization")

    def _next_request_id(self) -> str:
        with self._request_lock:
            self._request_number += 1
            return f"REQ-C05-{self._request_number:06d}"
