"""Bounded run lifecycle around Strands without scenario-specific tool selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from queue import Empty, Queue
from threading import Thread
from typing import Callable

from incidentpilot.agent.events import AgentEventType, RunBudget, RunTrace, TraceEvent
from incidentpilot.agent.strands_runtime import (
    AgentRuntime,
    AgentRuntimeFactory,
    StrandsDependencyError,
)
from incidentpilot.tools.session import IncidentToolSession


class AgentRunStatus(str, Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    AUTH_BLOCKED = "AUTH_BLOCKED"
    RUNTIME_BLOCKED = "RUNTIME_BLOCKED"


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    run_id: str
    status: AgentRunStatus
    detail: str
    final_text: str | None
    events: tuple[TraceEvent, ...]


class InvalidAgentResult(TypeError):
    """Raised when the runtime returns no usable terminal response."""


class AgentRunController:
    """Start, bound, and classify one run; never choose or order tools."""

    def __init__(
        self,
        *,
        trace: RunTrace,
        session: IncidentToolSession,
        runtime_factory: AgentRuntimeFactory,
        budget: RunBudget | None = None,
        terminal_commit: Callable[
            [Callable[[bool], AgentRunResult]], AgentRunResult
        ] | None = None,
    ) -> None:
        if session.trace is not trace:
            raise ValueError("controller, session, and trace must share one run")
        self._trace = trace
        self._session = session
        self._runtime_factory = runtime_factory
        self._budget = budget or RunBudget(max_summary_chars=trace.max_summary_chars)
        self._terminal_commit = terminal_commit

    def run(self, goal: str) -> AgentRunResult:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must be a non-empty string")
        self._trace.start_run()
        try:
            runtime = self._runtime_factory.create(
                session=self._session,
                trace=self._trace,
                budget=self._budget,
            )
        except StrandsDependencyError:
            return self._finish_blocked(
                AgentRunStatus.RUNTIME_BLOCKED,
                "RUNTIME BLOCKED: strands-agents is unavailable in this execution environment.",
            )
        except Exception as error:
            if _is_auth_error(error):
                return self._finish_blocked(AgentRunStatus.AUTH_BLOCKED, _auth_blocked_detail())
            return self._finish_failure("Agent runtime initialization failed safely.")

        result_queue: Queue[tuple[str, object]] = Queue(maxsize=1)

        def invoke() -> None:
            try:
                result_queue.put(("result", runtime(goal)))
            except Exception as error:
                result_queue.put(("error", error))

        worker = Thread(target=invoke, name=f"incidentpilot-{self._trace.run_id}", daemon=True)
        worker.start()
        worker.join(self._budget.timeout_seconds)
        if worker.is_alive():
            self._session.close_action_admission()
            self._cancel(runtime)
            worker.join(self._budget.cancel_grace_seconds)
            externally_cancelled = (
                self._session.close_action_admission_and_wait_for_quiescence()
            )
            if externally_cancelled:
                return self._finish_cancelled()
            return self._finish_terminal(
                AgentRunStatus.TIMEOUT,
                "Agent run stopped at the configured timeout.",
            )

        if self._session.close_action_admission_and_wait_for_quiescence():
            return self._finish_cancelled()

        try:
            kind, value = result_queue.get_nowait()
        except Empty:
            return self._finish_failure("Agent runtime ended without a result.")
        if kind == "error":
            if isinstance(value, Exception) and _is_auth_error(value):
                return self._finish_blocked(AgentRunStatus.AUTH_BLOCKED, _auth_blocked_detail())
            if self._trace.budget_exceeded:
                return self._finish_budget_exceeded()
            return self._finish_failure("Agent runtime failed safely.")

        if self._trace.budget_exceeded:
            return self._finish_budget_exceeded()

        try:
            final_text = _terminal_text(value)
        except InvalidAgentResult:
            return self._finish_failure("Agent runtime returned an invalid terminal result.")

        verified_recovery = (
            self._trace.latest_verification_passed
            and not self._session.has_pending_authoritative_verification
        )
        if verified_recovery:
            status = AgentRunStatus.RESOLVED
            detail = "Incident recovery was proven by an authoritative verification result."
        elif self._session.has_pending_authoritative_verification:
            status = AgentRunStatus.UNRESOLVED
            detail = (
                "Agent stopped after an executed recovery action without the required "
                "authoritative verification observation."
            )
        else:
            status = AgentRunStatus.UNRESOLVED
            detail = "Agent stopped without a passing authoritative verification result."
        return self._finish_terminal(
            status,
            detail,
            final_text=final_text,
            verified_recovery=verified_recovery,
        )

    @staticmethod
    def _cancel(runtime: AgentRuntime) -> None:
        try:
            runtime.cancel()
        except Exception:
            return

    def _finish_blocked(self, status: AgentRunStatus, detail: str) -> AgentRunResult:
        return self._finish_terminal(status, detail)

    def _finish_failure(self, detail: str) -> AgentRunResult:
        return self._finish_terminal(AgentRunStatus.FAILED, detail)

    def _finish_budget_exceeded(self) -> AgentRunResult:
        detail = "Agent run stopped because a configured model or tool budget was reached."
        return self._finish_terminal(AgentRunStatus.BUDGET_EXCEEDED, detail)

    def _finish_cancelled(self) -> AgentRunResult:
        return self._finish_terminal(
            AgentRunStatus.CANCELLED,
            "Agent run cancellation completed after admitted actions became quiescent.",
        )

    def _finish_terminal(
        self,
        status: AgentRunStatus,
        detail: str,
        *,
        final_text: str | None = None,
        verified_recovery: bool = False,
    ) -> AgentRunResult:
        # Never hold the API cancellation/commit boundary while an action is running.
        self._session.close_action_admission_and_wait_for_quiescence()

        def commit(externally_cancelled: bool) -> AgentRunResult:
            return self._session.commit_terminal(
                lambda session_cancelled: self._emit_terminal(
                    status,
                    detail,
                    final_text=final_text,
                    verified_recovery=verified_recovery,
                    cancelled=externally_cancelled or session_cancelled,
                )
            )

        if self._terminal_commit is not None:
            return self._terminal_commit(commit)
        return commit(False)

    def _emit_terminal(
        self,
        status: AgentRunStatus,
        detail: str,
        *,
        final_text: str | None,
        verified_recovery: bool,
        cancelled: bool,
    ) -> AgentRunResult:
        # Only invoked inside the shared commit operation; do not call runtime/user code here.
        if cancelled or status is AgentRunStatus.CANCELLED:
            status = AgentRunStatus.CANCELLED
            detail = "Agent run cancellation completed after admitted actions became quiescent."
            final_text = None
            verified_recovery = False
        if status is AgentRunStatus.TIMEOUT:
            event_type = AgentEventType.RUN_TIMEOUT
        elif status in {
            AgentRunStatus.RESOLVED,
            AgentRunStatus.UNRESOLVED,
            AgentRunStatus.BUDGET_EXCEEDED,
        }:
            event_type = AgentEventType.RUN_COMPLETED
        else:
            event_type = AgentEventType.RUN_FAILED
        payload: dict[str, object] = {
            "status": status.value,
            "verified_recovery": verified_recovery,
        }
        if status is AgentRunStatus.TIMEOUT:
            payload["timeout_seconds"] = self._budget.timeout_seconds
        self._trace.emit(
            event_type,
            "Agent run committed its terminal state after action quiescence.",
            payload,
        )
        return AgentRunResult(
            run_id=self._trace.run_id,
            status=status,
            detail=detail,
            final_text=final_text,
            events=self._trace.events,
        )


def _terminal_text(value: object) -> str:
    if value is None:
        raise InvalidAgentResult("terminal result is None")
    if isinstance(value, str):
        text = value.strip()
    else:
        if type(value).__str__ is object.__str__:
            raise InvalidAgentResult("terminal result has no text representation")
        text = str(value).strip()
    if not text:
        raise InvalidAgentResult("terminal result text is empty")
    return text[:2000]


def _is_auth_error(error: Exception) -> bool:
    identity = f"{type(error).__module__}.{type(error).__name__}".lower()
    message = str(error).lower()
    tokens = (
        "nocredentials",
        "credentialretrieval",
        "unauthorized",
        "accessdenied",
        "unrecognizedclient",
        "expiredtoken",
        "invalidsignature",
        "model access",
        "not authorized",
        "could not load credentials",
        "unable to locate credentials",
    )
    return any(token in identity or token in message for token in tokens)


def _auth_blocked_detail() -> str:
    return (
        "AUTH BLOCKED: model credentials or model access are unavailable; configure them outside "
        "the repository and rerun the C05 smoke gate."
    )
