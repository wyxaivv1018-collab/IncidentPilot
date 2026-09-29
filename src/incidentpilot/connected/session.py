"""Generic evidence, guarded actions, independent verification and same-run reports."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from incidentpilot.connected.connectors import Connector
from incidentpilot.safety import (
    ActionScope, ActionSpec, ApprovalRegistry, ExecutionGuard, GuardedActionExecutor,
    RiskLevel, SafetyActionRequest, SafetyEvidenceRegistry, SafetyPolicy,
)


class ConnectedSession:
    def __init__(self, connector: Connector, directory: Path, *, permission: bool,
                 mode: str = "live", method: str = "incidentpilot"):
        if mode not in {"live", "offline-test", "fixed-sop"}:
            raise ValueError("Unknown execution mode")
        self.run_id = "RUN-NEBIUS-" + uuid4().hex[:12]
        self.connector = connector
        self.permission = permission
        self.mode = mode
        self.method = method
        self.directory = directory / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.events: list[dict] = []
        self._lock = threading.RLock()
        self._origins: dict[str, dict] = {}
        self._active_origin: str | None = None
        self._evidence: dict[str, dict] = {}
        self.last_verification: dict | None = None
        self.summary: dict | None = None
        self.cancelled = False
        self.started = time.monotonic()
        self.tool_count = 0
        self.model_turns = 0
        self.terminal = False
        catalog = {name: ActionSpec(
            action=name, risk=RiskLevel.LOW, allowed_incident_ids=(self.run_id,),
            allowed_targets=(connector.system_id,), max_scope_size=1,
            exact_scope=ActionScope((connector.system_id,)), max_executions_per_run=2,
        ) for name in connector.actions} if permission else {}
        self.guard = ExecutionGuard(SafetyPolicy(ApprovalRegistry(), SafetyEvidenceRegistry(),
                                                catalog=catalog), tuple(
            GuardedActionExecutor(name, lambda request: connector.execute(request.action))
            for name in connector.actions))
        self.emit("run.started", {"mode": mode, "method": method,
                                  "system": connector.system_id, "permission": permission})

    def emit(self, kind: str, data: dict) -> dict:
        with self._lock:
            event = {"id": f"E{len(self.events)+1}", "sequence": len(self.events)+1,
                     "run_id": self.run_id, "type": kind,
                     "time": datetime.now(timezone.utc).isoformat(), "data": data}
            self.events.append(event)
            with (self.directory / "events.jsonl").open("a", encoding="utf8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            return event

    def register_origin(self, tool_use: dict):
        """SDK hook only: preserve the provider's original toolUseId and arguments."""
        call_id = tool_use.get("toolUseId")
        if (not isinstance(call_id, str) or not call_id or call_id in self._origins
                or not isinstance(tool_use.get("input"), dict)):
            raise ValueError("Missing or reused provider tool-call origin")
        self._origins[call_id] = dict(tool_use)
        self._active_origin = call_id
        self.emit("tool.requested", {**tool_use, "model_turn": self.model_turns,
                                    "origin": "provider" if self.mode == "live" else self.mode})

    def _enter(self, tool: str, arguments: dict):
        if self.cancelled or self.terminal or time.monotonic()-self.started > 240:
            raise RuntimeError("Run stopped")
        self.tool_count += 1
        if self.tool_count > 24:
            raise RuntimeError("Tool budget exhausted")
        if self.mode == "live":
            origin = self._origins.get(self._active_origin, {})
            if (origin.get("name") != tool or origin.get("consumed")
                    or origin.get("input") != arguments):
                raise PermissionError("Tool has no fresh matching provider origin")
            origin["consumed"] = True

    def describe(self):
        self._enter("describe_system", {})
        return {"system": self.connector.system_id, "title": self.connector.title,
                "sources": ["status", "logs"], "actions": self.connector.actions,
                "mutation_permission": self.permission, "scope": "owned test resource only"}

    def read(self, source: str):
        self._enter("read_evidence", {"source": source})
        if source not in {"status", "logs"}:
            return {"error": "Choose status or logs"}
        data = self.connector.read(source)
        event = self.emit("evidence.read", {"source": source, **data})
        self._evidence[event["id"]] = event
        return {"evidence_id": event["id"], **data}

    def act(self, action: str, evidence_ids: list[str], explanation: str):
        self._enter("perform_action", {"action": action, "evidence_ids": evidence_ids,
                                       "explanation": explanation})
        if (not explanation.strip() or len(explanation) > 1200 or not evidence_ids
                or not all(ref in self._evidence and self._evidence[ref]["data"].get("available")
                           for ref in evidence_ids)):
            return self.emit("action.denied", {"reason": "Current-run readable evidence and explanation required."})
        self.emit("decision.recorded", {"action": action, "evidence_ids": evidence_ids,
                                        "explanation": explanation, "provider_call_id": self._active_origin})
        request = SafetyActionRequest(request_id=uuid4().hex, run_id=self.run_id,
                                      incident_id=self.run_id, action=action,
                                      target=self.connector.system_id,
                                      scope=ActionScope((self.connector.system_id,)))
        self.last_verification = None
        result = self.guard.execute(request)
        event = self.emit("action.executed" if result.executed else "action.denied", {
            "action": action, "executed": result.executed,
            "guard_decision": result.evaluation.decision.value,
            "guard_reason": result.evaluation.reason.value,
            "operation_result": result.executor_result,
            "provider_call_id": self._active_origin,
        })
        if result.executed and self.method == "incidentpilot":
            # Observe real state synchronously; never choose the next corrective action.
            return {"action": event["data"], "verification": self._verify()}
        return event["data"]

    def _verify(self):
        result = self.connector.verify()
        event = self.emit("verification.result", result)
        self.last_verification = {"evidence_id": event["id"], **result}
        self._evidence[event["id"]] = {**event, "data": {**result, "available": result["status"] != "UNKNOWN"}}
        return self.last_verification

    def verify(self):
        self._enter("verify_recovery", {})
        return self._verify()

    def finish(self, problem: str, work_done: str, next_step: str):
        self._enter("finish_report", {"problem": problem, "work_done": work_done,
                                     "next_step": next_step})
        if any(not isinstance(x, str) or not x.strip() or len(x) > 1600
               for x in (problem, work_done, next_step)):
            return {"error": "Provide three concise nonempty report fields"}
        proof = self._verify()
        self.summary = {"problem": problem, "work_done": work_done, "next_step": next_step,
                        "attribution": "model interpretation" if self.mode == "live" else self.mode}
        self.terminal = True
        return {"status": "RESOLVED" if proof["status"] == "PASSED" else "HUMAN_HANDOFF"}

    def report(self, *, error: str | None = None, cost: dict | None = None):
        passed = bool(self.last_verification and self.last_verification["status"] == "PASSED")
        if error or self.cancelled:
            passed = False
        actions = [e["data"]["action"] for e in self.events if e["type"] == "action.executed"]
        payload = {
            "schema_version": "2.0", "run_id": self.run_id, "system": self.connector.system_id,
            "mode": self.mode, "method": self.method,
            "status": "RESOLVED" if passed else "HUMAN_HANDOFF",
            "verified": passed, "verification": self.last_verification,
            "summary": self.summary or {"problem": "Investigation did not produce a complete explanation.",
                                        "work_done": ", ".join(actions) or "No action executed.",
                                        "next_step": "Review the evidence with a human operator.",
                                        "attribution": "runtime fallback"},
            "executed_actions": actions, "error": error,
            "human_steps": 0 if passed else 1,
            "human_steps_definition": "Required operator handoff; not measured human repair effort.",
            "elapsed_seconds": round(time.monotonic()-self.started, 3),
            "model_turns": self.model_turns, "tool_calls": self.tool_count,
            "cost": cost or {"estimated_usd": 0, "unconfirmed_upper_usd": 0},
            "events": list(self.events),
        }
        (self.directory / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf8")
        return payload


def read_report(path: Path) -> dict:
    """Read old same-run JSON without rewriting historical contracts."""
    report = json.loads(path.read_text(encoding="utf8"))
    return {"format": "connected-v2" if report.get("schema_version") == "2.0" else "legacy-v1",
            "mode": "recorded", "report": report}
