"""Genuine Strands Agent core with bounded lifecycle and auditable provenance."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "AGENT_EVENT_SCHEMA_VERSION",
    "AgentEventType",
    "AgentRunController",
    "AgentRunResult",
    "AgentRunStatus",
    "RunBudget",
    "RunTrace",
    "StrandsAgentFactory",
    "StrandsDependencyError",
    "SummaryKind",
    "ToolInvocation",
    "TraceEvent",
    "TraceInvariantError",
]

_EVENT_EXPORTS = {
    "AGENT_EVENT_SCHEMA_VERSION",
    "AgentEventType",
    "RunBudget",
    "RunTrace",
    "SummaryKind",
    "ToolInvocation",
    "TraceEvent",
    "TraceInvariantError",
}
_CONTROLLER_EXPORTS = {"AgentRunController", "AgentRunResult", "AgentRunStatus"}
_RUNTIME_EXPORTS = {"StrandsAgentFactory", "StrandsDependencyError"}


def __getattr__(name: str) -> object:
    """Load public components lazily so the tool layer can import trace contracts safely."""
    if name in _EVENT_EXPORTS:
        return getattr(import_module("incidentpilot.agent.events"), name)
    if name in _CONTROLLER_EXPORTS:
        return getattr(import_module("incidentpilot.agent.controller"), name)
    if name in _RUNTIME_EXPORTS:
        return getattr(import_module("incidentpilot.agent.strands_runtime"), name)
    raise AttributeError(name)
