"""Reproducible cases and honest three-arm comparison on identical owned resources."""

import json
from pathlib import Path
from uuid import uuid4

from incidentpilot.connected.budget import BudgetLedger
from incidentpilot.connected.connectors import CASES, create_test_connector
from incidentpilot.connected.runtime import run_agent
from incidentpilot.connected.session import ConnectedSession


def run_sop(session: ConnectedSession):
    """Disclosed fixed SOP: read status/logs; restart listener or retry job; verify.

    This is a baseline/offline plumbing test, never a replacement for a model run.
    """
    system = session.describe()
    status = session.read("status")
    logs = session.read("logs")
    refs = [item["evidence_id"] for item in (status, logs) if item.get("available")]
    if system["mutation_permission"] and refs:
        action = "restart_service" if system["system"] == "http-app" else "retry_task"
        session.act(action, refs, "Fixed SOP: try the standard first recovery action.")
    verification = session.verify()
    session.finish("Fixed SOP inspection; consult attached status and logs.",
                   "Standard recovery attempted where evidence and permission allowed.",
                   "No action required." if verification["status"] == "PASSED"
                   else "Ask an operator to inspect the attached evidence and choose the next action.")
    return session.report()


def execute_case(case: str, root: Path, *, method: str = "incidentpilot",
                 mode: str = "live", description: str | None = None,
                 on_session=None):
    if case not in CASES or method not in {"incidentpilot", "generic", "sop"}:
        raise ValueError("Unknown case or comparison method")
    if mode not in {"live", "offline-test"}:
        raise ValueError("Unknown mode")
    spec = CASES[case]
    connector = create_test_connector(case, root / "services" / uuid4().hex)
    try:
        effective_mode = "fixed-sop" if method == "sop" else mode
        effective_method = "sop" if mode == "offline-test" else method
        session = ConnectedSession(connector, root / "runs", permission=spec["permission"],
                                   mode=effective_mode, method=effective_method)
        if on_session:
            on_session(session)
        if method == "sop" or mode == "offline-test":
            result = run_sop(session)
        else:
            result = run_agent(session, description or spec["description"],
                               BudgetLedger(root / "budget.sqlite"))
        return result
    finally:
        connector.close()


def compare(root: Path, *, live: bool):
    results = []
    methods = ("sop", "generic", "incidentpilot") if live else ("sop",)
    for case in CASES:
        for method in methods:
            result = execute_case(case, root, method=method,
                                  mode="live" if live else "offline-test")
            results.append({"case": case, **{k: result[k] for k in (
                "run_id", "method", "mode", "status", "elapsed_seconds", "executed_actions",
                "human_steps", "human_steps_definition", "model_turns", "tool_calls", "cost", "error")}})
            print(json.dumps(results[-1]), flush=True)
            if result["error"] and ("BUDGET" in result["error"] or "AUTH" in result["error"]):
                break
        else:
            continue
        break
    output = root / ("comparison-live.json" if live else "comparison-offline.json")
    output.write_text(json.dumps({"repetitions": 1, "randomized": False,
        "limitations": "Small sequential test, not a statistical win or measured human labor saving."
        " Same cases, descriptions, tools, permissions, model and limits."
        " IncidentPilot adds its evidence prompt and automatic post-action verification;"
        " generic uses the same guard and explicit verification tools.",
        "results": results}, indent=2), encoding="utf8")
    return output
