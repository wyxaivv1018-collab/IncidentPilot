"""Default C08 runner that preserves the reviewed C03-C06 execution path."""

from __future__ import annotations

from incidentpilot.agent import (
    AgentEventType,
    AgentRunController,
    AgentRunStatus,
    RunBudget,
    RunTrace,
)
from incidentpilot.agent.smoke import SmokeConfigurationError, build_deepseek_runtime_factory
from incidentpilot.agent.strands_runtime import (
    AgentRuntime,
    StrandsAgentFactory,
    StrandsDependencyError,
)
from incidentpilot.api.contracts import DemoRunCompletion
from incidentpilot.api.service import RunExecutionContext
from incidentpilot.memory.read_tools import KnowledgeReads
from incidentpilot.safety import ExecutionGuard, SafetyPolicy, simulator_executors
from incidentpilot.simulator import OrderSyncSimulator
from incidentpilot.tools import GuardedActionAdapter, IncidentToolSession, SimulatorReadAdapter


class _CancellationAwareRuntimeFactory:
    def __init__(
        self,
        delegate: StrandsAgentFactory,
        context: RunExecutionContext,
    ) -> None:
        self._delegate = delegate
        self._context = context

    def create(
        self,
        *,
        session: IncidentToolSession,
        trace: RunTrace,
        budget: RunBudget,
    ) -> AgentRuntime:
        runtime = self._delegate.create(session=session, trace=trace, budget=budget)
        self._context.register_cancel_hook(runtime.cancel)
        return runtime


class DefaultDemoRunner:
    """Run the frozen synthetic scenario through Strands and ExecutionGuard."""

    def __init__(
        self, *, budget: RunBudget | None = None, knowledge: KnowledgeReads | None = None,
    ) -> None:
        self._budget = budget or RunBudget()
        self._knowledge = knowledge or KnowledgeReads()

    def __call__(self, context: RunExecutionContext) -> DemoRunCompletion:
        simulator = OrderSyncSimulator()
        policy = SafetyPolicy(context.approvals, context.evidence)
        guard = ExecutionGuard(policy, simulator_executors(simulator))
        session = IncidentToolSession(
            run_id=context.run_id,
            knowledge=self._knowledge,
            trace=context.trace,
            reads=SimulatorReadAdapter(simulator),
            actions=GuardedActionAdapter(
                guard,
                incident_id=simulator.incident.incident_id,
            ),
        )
        context.register_cancel_hook(session.cancel)
        if context.cancellation.requested:
            return self._blocked_completion(
                context,
                AgentRunStatus.FAILED,
                "The run was cancelled before model initialization.",
            )
        try:
            runtime_factory = _CancellationAwareRuntimeFactory(
                build_deepseek_runtime_factory(),
                context,
            )
        except SmokeConfigurationError:
            return self._blocked_completion(
                context,
                AgentRunStatus.AUTH_BLOCKED,
                "AUTH BLOCKED: the external DeepSeek credential is unavailable.",
            )
        except StrandsDependencyError:
            return self._blocked_completion(
                context,
                AgentRunStatus.RUNTIME_BLOCKED,
                "RUNTIME BLOCKED: the reviewed Strands OpenAI provider is unavailable.",
            )

        controller = AgentRunController(
            trace=context.trace,
            session=session,
            runtime_factory=runtime_factory,
            budget=self._budget,
            terminal_commit=context.cancellation.commit_terminal,
        )
        incident = simulator.incident
        goal = (
            f"Investigate synthetic incident {incident.incident_id}: {incident.title}. "
            f"{incident.summary} Recover it only when typed evidence and policy permit."
        )
        result = controller.run(goal)
        return DemoRunCompletion(
            status=result.status,
            detail=result.detail,
            final_text=result.final_text,
        )

    @staticmethod
    def _blocked_completion(
        context: RunExecutionContext,
        status: AgentRunStatus,
        detail: str,
    ) -> DemoRunCompletion:
        def commit(cancelled: bool) -> DemoRunCompletion:
            final_status = AgentRunStatus.CANCELLED if cancelled else status
            context.trace.start_run()
            context.trace.emit(
                AgentEventType.RUN_FAILED,
                "The run was blocked before a model-backed completion.",
                {"status": final_status.value},
            )
            return DemoRunCompletion(
                final_status,
                "The run was cancelled before model initialization." if cancelled else detail,
            )

        return context.cancellation.commit_terminal(commit)
