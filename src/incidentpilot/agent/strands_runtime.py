"""Lazy Strands SDK integration and provenance hooks for the genuine model-tool loop."""

from __future__ import annotations

from threading import RLock
from typing import Protocol

from incidentpilot.agent.events import RunBudget, RunTrace, TraceInvariantError
from incidentpilot.agent.prompt import SYSTEM_PROMPT
from incidentpilot.tools.session import IncidentToolSession, ToolResponseStatus
from incidentpilot.tools.strands_tools import build_strands_tools


class StrandsDependencyError(RuntimeError):
    """Raised when the execution environment does not provide the Strands SDK."""


class AgentRuntime(Protocol):
    def __call__(self, prompt: str) -> object: ...

    def cancel(self) -> None: ...


class AgentRuntimeFactory(Protocol):
    def create(
        self,
        *,
        session: IncidentToolSession,
        trace: RunTrace,
        budget: RunBudget,
    ) -> AgentRuntime: ...


class StrandsTraceHooks:
    """Map SDK lifecycle events to immutable model-turn and tool-call evidence."""

    def __init__(
        self,
        trace: RunTrace,
        budget: RunBudget,
        session: IncidentToolSession | None = None,
    ) -> None:
        self._trace = trace
        self._budget = budget
        self._session = session
        self._last_model_turn_id: str | None = None
        self._lock = RLock()

    def before_model_call(self, event: object) -> None:
        with self._lock:
            if (
                self._session is not None
                and self._session.has_pending_authoritative_verification
            ):
                self._last_model_turn_id = None
                self._cancel_agent(
                    event,
                    "Post-action authoritative verification did not complete.",
                )
                return
            if self._trace.model_turn_count >= self._budget.max_model_turns:
                self._trace.record_budget_exceeded(
                    "model_turns",
                    self._budget.max_model_turns,
                )
                self._last_model_turn_id = None
                self._cancel_agent(event, "Model-turn budget was exhausted.")
                return
            self._last_model_turn_id = self._trace.start_model_turn()

    def after_model_call(self, event: object) -> None:
        with self._lock:
            if self._last_model_turn_id is None:
                return
            status = "error" if getattr(event, "exception", None) is not None else "completed"
            self._trace.complete_model_turn(self._last_model_turn_id, status=status)

    def before_tool_call(self, event: object) -> None:
        with self._lock:
            if self._last_model_turn_id is None:
                setattr(event, "cancel_tool", "Tool request lacked a model-turn origin.")
                return
            if self._trace.tool_call_count >= self._budget.max_tool_calls:
                self._trace.record_budget_exceeded("tool_calls", self._budget.max_tool_calls)
                setattr(event, "cancel_tool", "IncidentPilot tool-call budget exhausted.")
                return
            tool_use = getattr(event, "tool_use", None)
            if not isinstance(tool_use, dict):
                setattr(event, "cancel_tool", "Tool request provenance was malformed.")
                return
            tool_call_id = tool_use.get("toolUseId")
            tool_name = tool_use.get("name")
            arguments = tool_use.get("input", {})
            if (
                not isinstance(tool_call_id, str)
                or not tool_call_id.strip()
                or not isinstance(tool_name, str)
                or not tool_name.strip()
                or not isinstance(arguments, dict)
            ):
                setattr(event, "cancel_tool", "Tool request provenance was malformed.")
                return
            try:
                self._trace.record_tool_request(
                    self._last_model_turn_id,
                    tool_call_id,
                    tool_name,
                    arguments,
                )
            except (TraceInvariantError, TypeError, ValueError):
                setattr(event, "cancel_tool", "Tool request provenance was rejected.")

    def after_tool_call(self, event: object) -> None:
        tool_use = getattr(event, "tool_use", None)
        if not isinstance(tool_use, dict):
            return
        tool_call_id = tool_use.get("toolUseId")
        if not isinstance(tool_call_id, str) or self._trace.has_tool_result(tool_call_id):
            return
        try:
            invocation = self._trace.resolve_tool_invocation(tool_call_id)
        except TraceInvariantError:
            return
        failed = getattr(event, "exception", None) is not None
        status = ToolResponseStatus.ERROR.value
        summary = (
            "Strands reported a tool execution failure."
            if failed
            else "Strands completed a tool call without a valid typed adapter result."
        )
        self._trace.record_tool_result(
            invocation,
            status=status,
            summary=summary,
            payload={"error": True, "sdk_exception": failed, "adapter_result_missing": True},
        )

    @staticmethod
    def _cancel_agent(event: object, reason: str) -> None:
        agent = getattr(event, "agent", None)
        cancel = getattr(agent, "cancel", None)
        if not callable(cancel):
            raise TraceInvariantError(
                f"Strands model event omitted the Agent cancellation boundary: {reason}"
            )
        cancel()


class _StrandsRuntime:
    def __init__(self, agent: object) -> None:
        self._agent = agent

    def __call__(self, prompt: str) -> object:
        return self._agent(prompt)  # type: ignore[operator]

    def cancel(self) -> None:
        cancel = getattr(self._agent, "cancel", None)
        if callable(cancel):
            cancel()


class StrandsAgentFactory:
    """Build one real Strands Agent; dependency loading stays outside normal test imports."""

    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        *,
        model_id: str | None = None,
        model_provider: object | None = None,
    ) -> None:
        if model_id is not None and (not isinstance(model_id, str) or not model_id.strip()):
            raise ValueError("model_id must be None or a non-empty string")
        if model_id is not None and model_provider is not None:
            raise ValueError("model_id and model_provider are mutually exclusive")
        self._model_id = model_id
        self._model_provider = model_provider

    def create(
        self,
        *,
        session: IncidentToolSession,
        trace: RunTrace,
        budget: RunBudget,
    ) -> AgentRuntime:
        try:
            from strands import Agent, tool
            from strands.hooks import (
                AfterModelCallEvent,
                AfterToolCallEvent,
                BeforeModelCallEvent,
                BeforeToolCallEvent,
            )
        except ImportError as error:
            raise StrandsDependencyError(
                "strands-agents is not installed in the execution environment"
            ) from error

        tools = build_strands_tools(session, trace, tool_decorator=tool)
        kwargs: dict[str, object] = {
            "tools": list(tools),
            "system_prompt": self.system_prompt,
            "callback_handler": None,
            "retry_strategy": None,
        }
        if self._model_provider is not None:
            kwargs["model"] = self._model_provider
        elif self._model_id is not None:
            kwargs["model"] = self._model_id
        agent = Agent(**kwargs)
        hooks = StrandsTraceHooks(trace, budget, session)
        agent.add_hook(hooks.before_model_call, BeforeModelCallEvent)
        agent.add_hook(hooks.after_model_call, AfterModelCallEvent)
        agent.add_hook(hooks.before_tool_call, BeforeToolCallEvent)
        agent.add_hook(hooks.after_tool_call, AfterToolCallEvent)
        return _StrandsRuntime(agent)
