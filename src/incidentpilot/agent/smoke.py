"""Credential-aware C05 smoke gate for the real Strands runtime."""

from __future__ import annotations

import os
from uuid import uuid4

from incidentpilot.agent.controller import AgentRunController, AgentRunStatus
from incidentpilot.agent.events import RunBudget, RunTrace
from incidentpilot.agent.strands_runtime import StrandsAgentFactory, StrandsDependencyError
from incidentpilot.safety import (
    ApprovalRegistry,
    ExecutionGuard,
    SafetyEvidenceRegistry,
    SafetyPolicy,
    simulator_executors,
)
from incidentpilot.simulator import OrderSyncSimulator
from incidentpilot.tools import GuardedActionAdapter, IncidentToolSession, SimulatorReadAdapter

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL_ID = "deepseek-v4-flash"


class SmokeConfigurationError(RuntimeError):
    """Raised when the external live-smoke configuration is unavailable."""


def build_deepseek_runtime_factory() -> StrandsAgentFactory:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if api_key is None or not api_key.strip():
        raise SmokeConfigurationError(
            "AUTH BLOCKED: DEEPSEEK_API_KEY is unavailable outside the repository."
        )
    try:
        from strands.models.openai import OpenAIModel
    except ImportError as error:
        raise StrandsDependencyError(
            "strands-agents OpenAI provider is unavailable in this execution environment"
        ) from error
    model = OpenAIModel(
        client_args={"api_key": api_key, "base_url": DEEPSEEK_BASE_URL},
        model_id=DEEPSEEK_MODEL_ID,
        params={
            "temperature": 0,
            "extra_body": {"thinking": {"type": "disabled"}},
        },
    )
    return StrandsAgentFactory(model_provider=model)


def main() -> int:
    run_id = f"RUN-C05-SMOKE-{uuid4().hex[:12]}"
    simulator = OrderSyncSimulator()
    policy = SafetyPolicy(ApprovalRegistry(), SafetyEvidenceRegistry())
    guard = ExecutionGuard(policy, simulator_executors(simulator))
    trace = RunTrace(run_id)
    session = IncidentToolSession(
        run_id=run_id,
        trace=trace,
        reads=SimulatorReadAdapter(simulator),
        actions=GuardedActionAdapter(guard, incident_id=simulator.incident.incident_id),
    )
    try:
        runtime_factory = build_deepseek_runtime_factory()
    except SmokeConfigurationError as error:
        print("B01_SMOKE_PROVIDER=strands.models.openai.OpenAIModel")
        print(f"B01_SMOKE_MODEL={DEEPSEEK_MODEL_ID}")
        print("C05_SMOKE_STATUS=AUTH_BLOCKED")
        print("C05_SMOKE_MODEL_TURNS=0")
        print("C05_SMOKE_TOOL_CALLS=0")
        print("C05_SMOKE_VERIFIED=false")
        print(str(error))
        return 2
    except StrandsDependencyError as error:
        print("B01_SMOKE_PROVIDER=strands.models.openai.OpenAIModel")
        print(f"B01_SMOKE_MODEL={DEEPSEEK_MODEL_ID}")
        print("C05_SMOKE_STATUS=RUNTIME_BLOCKED")
        print("C05_SMOKE_MODEL_TURNS=0")
        print("C05_SMOKE_TOOL_CALLS=0")
        print("C05_SMOKE_VERIFIED=false")
        print(str(error))
        return 2
    controller = AgentRunController(
        trace=trace,
        session=session,
        runtime_factory=runtime_factory,
        budget=RunBudget(),
    )
    incident = simulator.incident
    goal = (
        f"Investigate synthetic incident {incident.incident_id}: {incident.title}. "
        f"{incident.summary} Recover it only when typed evidence and policy permit."
    )
    result = controller.run(goal)
    print("B01_SMOKE_PROVIDER=strands.models.openai.OpenAIModel")
    print(f"B01_SMOKE_MODEL={DEEPSEEK_MODEL_ID}")
    print(f"C05_SMOKE_STATUS={result.status.value}")
    print(f"C05_SMOKE_MODEL_TURNS={trace.model_turn_count}")
    print(f"C05_SMOKE_TOOL_CALLS={trace.tool_call_count}")
    print(f"C05_SMOKE_VERIFIED={str(trace.has_passed_verification).lower()}")
    if result.status in (AgentRunStatus.RESOLVED, AgentRunStatus.UNRESOLVED):
        return 0
    if result.status is AgentRunStatus.AUTH_BLOCKED:
        print(result.detail)
        return 0
    if result.status is AgentRunStatus.RUNTIME_BLOCKED:
        print(result.detail)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
