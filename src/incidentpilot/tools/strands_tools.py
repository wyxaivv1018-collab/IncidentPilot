"""Strands-decorated wrappers over the typed IncidentToolSession."""

from __future__ import annotations

from typing import Any, Callable, Literal

from incidentpilot.agent.events import RunTrace, ToolInvocation, TraceInvariantError
from incidentpilot.tools.session import IncidentToolSession

ToolDecorator = Callable[..., object]


def build_strands_tools(
    session: IncidentToolSession,
    trace: RunTrace,
    *,
    tool_decorator: ToolDecorator,
) -> tuple[object, ...]:
    """Create model-visible functions; the Strands model selects which one to call."""
    if session.trace is not trace:
        raise ValueError("Strands tools and session must share one trace")

    def invocation(tool_context: Any, expected_name: str) -> ToolInvocation:
        tool_use = getattr(tool_context, "tool_use", None)
        if not isinstance(tool_use, dict):
            raise TraceInvariantError("Strands ToolContext omitted tool_use provenance")
        tool_call_id = tool_use.get("toolUseId")
        tool_name = tool_use.get("name")
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            raise TraceInvariantError("Strands ToolContext omitted toolUseId")
        if tool_name != expected_name:
            raise TraceInvariantError("Strands ToolContext tool name changed before execution")
        recorded = trace.resolve_tool_invocation(tool_call_id)
        if recorded.tool_name != expected_name:
            raise TraceInvariantError("recorded tool request does not match executed tool")
        return recorded

    def read_incident(tool_context: Any) -> dict[str, object]:
        """Read the immutable incident identity and user-visible incident goal."""
        return session.read_incident(invocation(tool_context, "read_incident")).as_dict()

    def read_logs(tool_context: Any) -> dict[str, object]:
        """Read the log findings currently observable in the synthetic environment."""
        return session.read_logs(invocation(tool_context, "read_logs")).as_dict()

    def read_environment(tool_context: Any) -> dict[str, object]:
        """Read current worker, database, cache-observation, and sync-job state."""
        return session.read_environment(invocation(tool_context, "read_environment")).as_dict()

    def lookup_historical_memory(
        query: str, tool_context: Any, limit: int = 5,
    ) -> dict[str, object]:
        """Search prior local incidents by symptom/service/evidence token (1..256 chars,
        limit 1..5). Historical evidence is not current fact or recovery verification.
        Errors indicate unavailable knowledge, not an incident finding.
        """
        return session.lookup_historical_memory(
            invocation(tool_context, "lookup_historical_memory"), query=query, limit=limit,
        ).as_dict()

    def lookup_sop(
        query: str, tool_context: Any, limit: int = 5,
    ) -> dict[str, object]:
        """Search official synthetic-demo-sop knowledge (query 1..256 chars, limit 1..5).
        Suggestions only: no actions executed, permissions granted or recovery proven.
        Errors indicate unavailable knowledge, not an incident finding.
        """
        return session.lookup_sop(
            invocation(tool_context, "lookup_sop"), query=query, limit=limit,
        ).as_dict()

    def verify_recovery(tool_context: Any) -> dict[str, object]:
        """Read an on-demand authoritative state; executed actions are verified automatically."""
        return session.verify_recovery(invocation(tool_context, "verify_recovery")).as_dict()

    def restart_noncritical_worker(
        target: Literal["sync-worker"],
        tool_context: Any,
    ) -> dict[str, object]:
        """Restart the exact stopped worker; the runtime returns an automatic verification."""
        return session.restart_noncritical_worker(
            invocation(tool_context, "restart_noncritical_worker"),
            target=target,
        ).as_dict()

    def clear_application_cache(
        target: Literal["order-sync"],
        max_keys: int,
        tool_context: Any,
    ) -> dict[str, object]:
        """Clear at most 100 keys from observable evidence; return automatic verification."""
        return session.clear_application_cache(
            invocation(tool_context, "clear_application_cache"),
            target=target,
            max_keys=max_keys,
        ).as_dict()

    def retry_sync_job(
        target: Literal["order-sync-job-001"],
        tool_context: Any,
    ) -> dict[str, object]:
        """Retry only while the worker is running; return outcome plus automatic verification."""
        return session.retry_sync_job(
            invocation(tool_context, "retry_sync_job"),
            target=target,
        ).as_dict()

    def record_decision_summary(
        kind: Literal["plan", "replan", "rationale"],
        summary: str,
        evidence_event_ids: list[str],
        tool_context: Any,
    ) -> dict[str, object]:
        """Record plan/replan/rationale with tool or verification evidence; use rationale at end."""
        return session.record_decision_summary(
            invocation(tool_context, "record_decision_summary"),
            kind=kind,
            summary=summary,
            evidence_event_ids=tuple(evidence_event_ids),
        ).as_dict()

    definitions = (
        ("lookup_historical_memory", lookup_historical_memory),
        ("lookup_sop", lookup_sop),
        ("read_incident", read_incident),
        ("read_logs", read_logs),
        ("read_environment", read_environment),
        ("verify_recovery", verify_recovery),
        ("restart_noncritical_worker", restart_noncritical_worker),
        ("clear_application_cache", clear_application_cache),
        ("retry_sync_job", retry_sync_job),
        ("record_decision_summary", record_decision_summary),
    )
    summary_schema = {"json": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["plan", "replan", "rationale"]},
            "summary": {
                "type": "string",
                "minLength": 1,
                "maxLength": trace.max_summary_chars,
                "pattern": r"\S",
                "description": (
                    f"Non-blank summary, at most {trace.max_summary_chars} characters."
                ),
            },
            "evidence_event_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Prior substantive tool.result or verification.result event IDs.",
            },
        },
        "required": ["kind", "summary", "evidence_event_ids"],
    }}
    return tuple(
        tool_decorator(
            name=name,
            context=True,
            **({"inputSchema": summary_schema} if name == "record_decision_summary" else {}),
        )(function)
        for name, function in definitions
    )
