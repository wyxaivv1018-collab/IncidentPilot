"""Thread-safe application service behind the C08 local demo API."""

from __future__ import annotations

import re
import os
import traceback
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Condition, Event, RLock, Thread
from typing import Callable, Protocol, TypeVar
from uuid import uuid4

from incidentpilot.agent import AgentEventType, AgentRunStatus, RunTrace
from incidentpilot.agent.events import TraceInvariantError
from incidentpilot.agent.redaction import redact_text
from incidentpilot.api.approvals import ApprovalCoordinator, PendingApprovalStatus
from incidentpilot.api.contracts import (
    ACTIVE_RUN_STATES,
    API_SCHEMA_VERSION,
    DEMO_SCENARIO_ID,
    TERMINAL_RUN_STATES,
    ApiError,
    ApiErrorCode,
    DemoRunCompletion,
    RunState,
    run_state_from_agent,
    serialize_trace_event,
)
from incidentpilot.reporting.service import ArtifactBundle, ArtifactStore, build_artifacts
from incidentpilot.reporting.source import ArtifactSourceError, ArtifactValidationError
from incidentpilot.safety import (
    ActionArgument,
    ActionScope,
    ApprovalRegistry,
    SafetyActionRequest,
    SafetyEvidenceRegistry,
)

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CommitResult = TypeVar("_CommitResult")


class TerminalCommitStarted(RuntimeError):
    """Cancellation cannot replace a terminal winner."""


class RunCancellation:
    """Per-run arbitration: accepted cancellation or terminal commit wins permanently."""

    def __init__(self) -> None:
        self._requested = Event()
        self._lock = RLock()
        self._hooks: list[Callable[[], None]] = []
        self._terminalizing = False

    @property
    def requested(self) -> bool:
        return self._requested.is_set()

    def register_hook(self, hook: Callable[[], None]) -> None:
        if not callable(hook):
            raise TypeError("cancellation hook must be callable")
        invoke_now = False
        with self._lock:
            if self._requested.is_set():
                invoke_now = True
            elif not self._terminalizing:
                self._hooks.append(hook)
        if invoke_now:
            self._invoke(hook)

    def request(self) -> bool:
        try:
            hooks = self.begin_request()
        except TerminalCommitStarted:
            return False
        if hooks is None:
            return False
        self.invoke_hooks(hooks)
        return True

    def begin_request(
        self,
        before_signal: Callable[[], None] | None = None,
    ) -> tuple[Callable[[], None], ...] | None:
        """Accept under the commit lock; callers dispatch returned hooks outside their locks."""
        with self._lock:
            if self._terminalizing:
                raise TerminalCommitStarted("The run has already entered terminal commit.")
            if self._requested.is_set():
                return None
            if before_signal is not None:
                before_signal()
            self._requested.set()
            hooks = tuple(self._hooks)
            self._hooks.clear()
            return hooks

    def commit_terminal(self, commit: Callable[[bool], _CommitResult]) -> _CommitResult:
        """Freeze the winner and perform its terminal write in the same critical section.

        Re-entry for final API validation observes the same immutable winner. A failed write
        does not reopen cancellation or permit a later request to rewrite history.
        """
        with self._lock:
            self._terminalizing = True
            self._hooks.clear()
            return commit(self._requested.is_set())

    def invoke_hooks(self, hooks: tuple[Callable[[], None], ...]) -> None:
        for hook in hooks:
            self._invoke(hook)

    @staticmethod
    def _invoke(hook: Callable[[], None]) -> None:
        try:
            hook()
        except Exception:
            return


@dataclass(frozen=True, slots=True)
class RunExecutionContext:
    """Trusted per-run capabilities; caller input never creates an action request."""

    run_id: str
    trace: RunTrace
    approvals: ApprovalRegistry
    evidence: SafetyEvidenceRegistry
    approval_coordinator: ApprovalCoordinator
    cancellation: RunCancellation

    def register_cancel_hook(self, hook: Callable[[], None]) -> None:
        self.cancellation.register_hook(hook)

    def request_approval(
        self,
        request: SafetyActionRequest,
        *,
        ttl_seconds: float = 60.0,
    ) -> dict[str, object]:
        if request.run_id != self.run_id:
            raise ValueError("approval request must belong to this run")
        return self.approval_coordinator.register(request, ttl_seconds=ttl_seconds)

    def wait_for_approval(
        self,
        approval_request_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> str | None:
        return self.approval_coordinator.wait_for_approval(
            approval_request_id,
            timeout_seconds=timeout_seconds,
        )


class DemoRunner(Protocol):
    def __call__(self, context: RunExecutionContext) -> DemoRunCompletion: ...


@dataclass(slots=True)
class _RunRecord:
    context: RunExecutionContext
    scenario_id: str
    status: RunState
    detail: str
    started_at: datetime
    completed_at: datetime | None = None
    final_text: str | None = None
    error: dict[str, object] | None = None
    artifacts_ready: bool = False
    worker: Thread | None = field(default=None, repr=False)
    diagnostics: list[dict[str, object]] = field(default_factory=list)


class DemoApiService:
    """Own one local demo run and publish only trace-derived artifacts."""

    def __init__(
        self,
        *,
        runner: DemoRunner,
        artifact_store: ArtifactStore,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not callable(runner):
            raise TypeError("runner must be callable")
        if not isinstance(artifact_store, ArtifactStore):
            raise TypeError("artifact_store must be an ArtifactStore")
        self._runner = runner
        self._artifact_store = artifact_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: f"RUN-C08-{uuid4().hex[:12]}")
        self._records: dict[str, _RunRecord] = {}
        self._active_run_id: str | None = None
        self._lock = RLock()
        self._condition = Condition(self._lock)

    @property
    def artifact_directory(self) -> Path:
        return self._artifact_store.base_directory

    def start_run(self, *, scenario_id: str = DEMO_SCENARIO_ID) -> dict[str, object]:
        if scenario_id != DEMO_SCENARIO_ID:
            raise ApiError(
                status_code=422,
                code=ApiErrorCode.SCENARIO_NOT_SUPPORTED,
                message="Only the frozen local order-sync demo scenario is supported.",
                details={"supported_scenario_id": DEMO_SCENARIO_ID},
            )
        now = self._now()
        with self._condition:
            if self._active_run_id is not None:
                active = self._records[self._active_run_id]
                if active.status in ACTIVE_RUN_STATES:
                    raise ApiError(
                        status_code=409,
                        code=ApiErrorCode.ACTIVE_RUN_EXISTS,
                        message="A demo run is already active; wait for it or cancel it first.",
                        retryable=True,
                        details={"run_id": active.context.run_id},
                    )
                self._active_run_id = None
            run_id = self._new_run_id()
            approvals = ApprovalRegistry()
            evidence = SafetyEvidenceRegistry()
            context = RunExecutionContext(
                run_id=run_id,
                trace=RunTrace(run_id),
                approvals=approvals,
                evidence=evidence,
                approval_coordinator=ApprovalCoordinator(
                    approvals,
                    evidence,
                    clock=self._clock,
                ),
                cancellation=RunCancellation(),
            )
            record = _RunRecord(
                context=context,
                scenario_id=scenario_id,
                status=RunState.STARTING,
                detail="The local demo run has been accepted and is starting.",
                started_at=now,
            )
            self._records[run_id] = record
            self._active_run_id = run_id
            worker = Thread(
                target=self._execute,
                args=(run_id,),
                name=f"incidentpilot-api-{run_id}",
                daemon=True,
            )
            record.worker = worker
            accepted = {
                "schema_version": API_SCHEMA_VERSION,
                "run_id": run_id,
                "scenario_id": scenario_id,
                "status": RunState.STARTING.value,
                "links": self._links(run_id),
            }
        try:
            worker.start()
        except Exception:
            with self._condition:
                record.status = RunState.FAILED
                record.detail = "The local run worker could not be started safely."
                record.error = self._error_value(ApiErrorCode.INTERNAL_ERROR)
                record.completed_at = self._now()
                self._active_run_id = None
                self._condition.notify_all()
            raise ApiError(
                status_code=500,
                code=ApiErrorCode.INTERNAL_ERROR,
                message="The local run worker could not be started safely.",
            ) from None
        return accepted

    def get_status(self, run_id: str) -> dict[str, object]:
        with self._condition:
            return self._status_value(self._record(run_id))

    def get_events(self, run_id: str, *, after: int = 0) -> dict[str, object]:
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise ApiError(
                status_code=422,
                code=ApiErrorCode.INVALID_EVENT_CURSOR,
                message="The event cursor must be a non-negative integer.",
            )
        with self._condition:
            record = self._record(run_id)
            if record.status in TERMINAL_RUN_STATES:
                try:
                    self._validate_terminal_trace(record.context.trace, record.status)
                except TraceInvariantError:
                    raise ApiError(
                        status_code=500,
                        code=ApiErrorCode.INTERNAL_ERROR,
                        message="The terminal audit record is inconsistent; events are unavailable.",
                    ) from None
            values = tuple(
                serialize_trace_event(event)
                for event in record.context.trace.events
                if event.sequence > after
            )
            next_after = values[-1]["sequence"] if values else after
            return {
                "schema_version": API_SCHEMA_VERSION,
                "run_id": run_id,
                "events": list(values),
                "next_after": next_after,
                "terminal": record.status in TERMINAL_RUN_STATES,
                "status": record.status.value,
            }

    def get_diagnostics(self, run_id: str) -> dict[str, object]:
        """Trusted local capture only; not an HTTP endpoint or accepted event stream.

        A rejected sealed trace stays rejected by get_events. This separate envelope
        preserves failure evidence without presenting it as valid terminal evidence.
        """
        with self._condition:
            record = self._record(run_id)
            try:
                self._validate_terminal_trace(record.context.trace, record.status)
                valid = True
            except TraceInvariantError:
                valid = False
            return {
                "diagnostic_only": True,
                "terminal_audit_valid": valid,
                "status": self._status_value(record),
                "failures": [dict(item) for item in record.diagnostics],
                "unvalidated_trace": [serialize_trace_event(e) for e in record.context.trace.events],
            }

    @staticmethod
    def _record_failure(record: _RunRecord, stage: str, error: Exception) -> None:
        if len(record.diagnostics) >= 8:
            return
        try:
            message = str(error)
        except Exception:
            message = "Exception message unavailable."
        for name, value in os.environ.items():
            if value and any(word in name.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
                message = message.replace(value, "[REDACTED]")
        record.diagnostics.append({
            "stage": stage, "exception_type": type(error).__name__,
            "message": redact_text(message)[:1000],
            "frames": [
                {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(error.__traceback__)[-8:]
            ],
        })

    def wait_for_events(
        self,
        run_id: str,
        *,
        after: int,
        timeout_seconds: float,
    ) -> dict[str, object]:
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        deadline = time.monotonic() + timeout_seconds
        while True:
            snapshot = self.get_events(run_id, after=after)
            if snapshot["events"] or snapshot["terminal"]:
                return snapshot
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return snapshot
            with self._condition:
                self._condition.wait(min(remaining, 0.05))

    def cancel_run(self, run_id: str) -> dict[str, object]:
        with self._condition:
            record = self._record(run_id)
            if record.status not in ACTIVE_RUN_STATES:
                raise ApiError(
                    status_code=409,
                    code=ApiErrorCode.RUN_NOT_ACTIVE,
                    message="The run is already terminal and cannot be cancelled.",
                )
            try:
                hooks = record.context.cancellation.begin_request(
                    lambda: record.context.approval_coordinator.cancel_run(run_id)
                )
            except TerminalCommitStarted:
                raise ApiError(
                    status_code=409,
                    code=ApiErrorCode.RUN_NOT_ACTIVE,
                    message="The run has entered terminal commit and cannot be cancelled.",
                ) from None
            record.status = RunState.CANCEL_REQUESTED
            record.detail = (
                "Cancellation was requested; the active slot remains held until the "
                "bounded worker stops."
            )
            self._condition.notify_all()
        if hooks is not None:
            record.context.cancellation.invoke_hooks(hooks)
        return self.get_status(run_id)

    def approve(
        self,
        run_id: str,
        approval_request_id: str,
        *,
        action: str,
        target: str,
        scope: ActionScope,
        arguments: tuple[ActionArgument, ...],
    ) -> dict[str, object]:
        with self._condition:
            record = self._record(run_id)
            if record.status not in {RunState.STARTING, RunState.RUNNING}:
                raise ApiError(
                    status_code=409,
                    code=ApiErrorCode.RUN_NOT_ACTIVE,
                    message="Approvals are accepted only while their run is active.",
                )
            value = record.context.approval_coordinator.approve(
                run_id=run_id,
                approval_request_id=approval_request_id,
                action=action,
                target=target,
                scope=scope,
                arguments=arguments,
            )
        return {"schema_version": API_SCHEMA_VERSION, "approval": value}

    def get_report(self, run_id: str) -> dict[str, object]:
        bundle = self._load_artifacts(run_id)
        return {
            "schema_version": API_SCHEMA_VERSION,
            "run_id": run_id,
            "report": dict(bundle.report),
            "report_markdown": bundle.report_markdown,
        }

    def get_memory(self, run_id: str) -> dict[str, object]:
        bundle = self._load_artifacts(run_id)
        return {
            "schema_version": API_SCHEMA_VERSION,
            "run_id": run_id,
            "memory": dict(bundle.memory),
        }

    def wait_for_terminal(
        self,
        run_id: str,
        *,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            record = self._record(run_id)
            while record.status not in TERMINAL_RUN_STATES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"run did not finish: {run_id}")
                self._condition.wait(remaining)
            return self._status_value(record)

    def _execute(self, run_id: str) -> None:
        with self._condition:
            record = self._records[run_id]
            if record.context.cancellation.requested:
                self._finish_cancelled(record)
                return
            record.status = RunState.RUNNING
            record.detail = "The local demo runner is active."
            self._condition.notify_all()

        completion: DemoRunCompletion | None = None
        final_state = RunState.FAILED
        detail = "The local demo runner failed safely."
        error: dict[str, object] | None = None
        artifacts_ready = False
        bundle_to_publish: ArtifactBundle | None = None
        try:
            completion = self._runner(record.context)
            if not isinstance(completion, DemoRunCompletion):
                raise TypeError("runner returned an invalid completion")
            # DefaultDemoRunner already committed under this boundary. Legacy/custom runners
            # are closed here, and any conflicting sealed claim is rejected below.
            record.context.cancellation.commit_terminal(lambda cancelled: cancelled)
            final_state = run_state_from_agent(completion.status)
            detail = completion.detail
            if record.context.cancellation.requested:
                final_state = RunState.CANCELLED
                detail = "The demo run was cancelled and all pending approvals were revoked."
            elif (
                final_state is RunState.RESOLVED
                and not record.context.trace.latest_verification_passed
            ):
                final_state = RunState.FAILED
                detail = (
                    "The runner claimed resolution without a final authoritative PASSED "
                    "verification; the API rejected the claim."
                )
                error = self._error_value(ApiErrorCode.RESOLUTION_PROOF_INVALID)
            elif final_state in {
                RunState.RESOLVED,
                RunState.UNRESOLVED,
                RunState.FAILED,
                RunState.TIMEOUT,
                RunState.BUDGET_EXCEEDED,
            }:
                try:
                    source = self._artifact_source(record, completion)
                    bundle_to_publish = build_artifacts(
                        source,
                        scenario_id=record.scenario_id,
                    )
                except (
                    ArtifactSourceError,
                    ArtifactValidationError,
                    FileExistsError,
                    OSError,
                ) as exc:
                    self._record_failure(record, "artifact_generation", exc)
                    if final_state is RunState.RESOLVED:
                        final_state = RunState.FAILED
                        detail = (
                            "The resolved trace could not produce a valid C07 artifact pair; "
                            "the API rejected the terminal claim."
                        )
                        error = self._error_value(
                            ApiErrorCode.ARTIFACT_GENERATION_FAILED
                        )
        except Exception as exc:
            self._record_failure(record, "runner", exc)
            final_state = RunState.FAILED
            detail = "The local demo runner failed safely."
            error = self._error_value(ApiErrorCode.INTERNAL_ERROR)
            bundle_to_publish = None

        record.context.approval_coordinator.cancel_run(run_id)
        with self._condition:
            record.context.cancellation.commit_terminal(lambda cancelled: cancelled)
            if record.context.cancellation.requested:
                final_state = RunState.CANCELLED
                detail = "The demo run was cancelled and all pending approvals were revoked."
                error = None
                artifacts_ready = False
                bundle_to_publish = None
            try:
                self._ensure_terminal_trace(record.context.trace, final_state)
            except TraceInvariantError as exc:
                self._record_failure(record, "terminal_audit_before_publication", exc)
                bundle_to_publish = None
                error = error or self._error_value(ApiErrorCode.INTERNAL_ERROR)
                detail = "The terminal audit record is inconsistent; the API rejected the claim."
                if final_state is RunState.RESOLVED:
                    final_state = RunState.FAILED
            if bundle_to_publish is not None:
                try:
                    self._artifact_store.save(bundle_to_publish)
                    artifacts_ready = True
                except Exception as exc:
                    self._record_failure(record, "artifact_publication", exc)
                    artifacts_ready = False
                    if final_state is RunState.RESOLVED:
                        final_state = RunState.FAILED
                        detail = (
                            "The resolved trace could not publish a valid C07 artifact pair; "
                            "the API rejected the terminal claim."
                        )
                        error = self._error_value(
                            ApiErrorCode.ARTIFACT_GENERATION_FAILED
                        )
            try:
                self._ensure_terminal_trace(record.context.trace, final_state)
            except TraceInvariantError as exc:
                self._record_failure(record, "terminal_audit_after_publication", exc)
                artifacts_ready = False
                error = error or self._error_value(ApiErrorCode.INTERNAL_ERROR)
            record.status = final_state
            record.detail = detail
            record.final_text = (
                completion.final_text if completion is not None and error is None else None
            )
            record.error = error
            record.artifacts_ready = artifacts_ready
            record.completed_at = self._now()
            if self._active_run_id == run_id:
                self._active_run_id = None
            self._condition.notify_all()

    def _finish_cancelled(self, record: _RunRecord) -> None:
        record.context.approval_coordinator.cancel_run(record.context.run_id)
        self._ensure_terminal_trace(record.context.trace, RunState.CANCELLED)
        record.status = RunState.CANCELLED
        record.detail = "The demo run was cancelled before the runner started."
        record.completed_at = self._now()
        if self._active_run_id == record.context.run_id:
            self._active_run_id = None
        self._condition.notify_all()

    def _load_artifacts(self, run_id: str):
        with self._condition:
            record = self._record(run_id)
            if not record.artifacts_ready:
                raise ApiError(
                    status_code=409,
                    code=ApiErrorCode.ARTIFACT_NOT_READY,
                    message="A validated artifact pair is not available for this run.",
                    retryable=record.status in ACTIVE_RUN_STATES,
                )
        try:
            return self._artifact_store.load(run_id)
        except (ArtifactValidationError, OSError):
            raise ApiError(
                status_code=500,
                code=ApiErrorCode.ARTIFACT_INVALID,
                message="The persisted artifact pair failed strict validation.",
            ) from None

    def _artifact_source(
        self,
        record: _RunRecord,
        completion: DemoRunCompletion,
    ) -> dict[str, object]:
        passed = record.context.trace.latest_verification_passed
        return {
            "schema_version": "1.0",
            "run_id": record.context.run_id,
            "trace": {
                "events": [
                    serialize_trace_event(event) for event in record.context.trace.events
                ]
            },
            "result": {
                "status": completion.status.value,
                "detail": completion.detail,
                "final_text": completion.final_text,
                "authoritative_pass_observed": passed,
                "verified_recovery": (
                    completion.status is AgentRunStatus.RESOLVED and passed
                ),
            },
        }

    @staticmethod
    def _ensure_terminal_trace(trace: RunTrace, final_state: RunState) -> None:
        if trace.sealed:
            DemoApiService._validate_terminal_trace(trace, final_state)
            return
        if not trace.events:
            trace.start_run()
        if final_state is RunState.TIMEOUT:
            event_type = AgentEventType.RUN_TIMEOUT
        elif final_state in {
            RunState.RESOLVED,
            RunState.UNRESOLVED,
            RunState.BUDGET_EXCEEDED,
        }:
            event_type = AgentEventType.RUN_COMPLETED
        else:
            event_type = AgentEventType.RUN_FAILED
        trace.emit(
            event_type,
            "The API sealed the terminal run trace.",
            {
                "status": final_state.value,
                "verified_recovery": (
                    final_state is RunState.RESOLVED
                    and trace.latest_verification_passed
                ),
            },
        )

    @staticmethod
    def _validate_terminal_trace(trace: RunTrace, final_state: RunState) -> None:
        if final_state is RunState.TIMEOUT:
            expected_type = AgentEventType.RUN_TIMEOUT
        elif final_state in {
            RunState.RESOLVED,
            RunState.UNRESOLVED,
            RunState.BUDGET_EXCEEDED,
        }:
            expected_type = AgentEventType.RUN_COMPLETED
        else:
            expected_type = AgentEventType.RUN_FAILED
        events = trace.events
        if (
            not trace.sealed
            or not events
            or events[-1].event_type is not expected_type
            or events[-1].payload.get("status") != final_state.value
        ):
            raise TraceInvariantError("sealed terminal does not match the API final state")

    def _status_value(self, record: _RunRecord) -> dict[str, object]:
        events = record.context.trace.events
        approvals = record.context.approval_coordinator.for_run(record.context.run_id)
        pending = [
            approval
            for approval in approvals
            if approval["status"] == PendingApprovalStatus.PENDING.value
        ]
        return {
            "schema_version": API_SCHEMA_VERSION,
            "run_id": record.context.run_id,
            "scenario_id": record.scenario_id,
            "status": record.status.value,
            "detail": record.detail,
            "active": record.status in ACTIVE_RUN_STATES,
            "cancel_requested": record.context.cancellation.requested,
            "event_count": len(events),
            "last_event_id": events[-1].event_id if events else None,
            "report_available": record.artifacts_ready,
            "memory_available": record.artifacts_ready,
            "pending_approvals": pending,
            "started_at": record.started_at.isoformat(),
            "completed_at": (
                record.completed_at.isoformat()
                if record.completed_at is not None
                else None
            ),
            "final_text": record.final_text,
            "error": dict(record.error) if record.error is not None else None,
            "links": self._links(record.context.run_id),
        }

    def _record(self, run_id: str) -> _RunRecord:
        record = self._records.get(run_id)
        if record is None:
            raise ApiError(
                status_code=404,
                code=ApiErrorCode.RUN_NOT_FOUND,
                message="The requested demo run was not found.",
            )
        return record

    def _new_run_id(self) -> str:
        run_id = self._id_factory()
        if not isinstance(run_id, str) or _SAFE_RUN_ID.fullmatch(run_id) is None:
            raise ValueError("run id factory returned an unsafe identifier")
        if run_id in self._records:
            raise ValueError("run id factory returned a duplicate identifier")
        return run_id

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("service clock must return datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("service clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _error_value(code: ApiErrorCode) -> dict[str, object]:
        return {"code": code.value, "retryable": False}

    @staticmethod
    def _links(run_id: str) -> dict[str, str]:
        base = f"/api/v1/runs/{run_id}"
        return {
            "status": base,
            "events": f"{base}/events",
            "event_stream": f"{base}/events/stream",
            "cancel": f"{base}/cancel",
            "report": f"{base}/report",
            "memory": f"{base}/memory",
        }
