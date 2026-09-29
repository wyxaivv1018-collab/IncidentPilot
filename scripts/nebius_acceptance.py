"""Read-only acceptance of new live evidence; offline/mock/historical runs never qualify."""

import json
from pathlib import Path

from incidentpilot.connected.budget import MODEL_ID
from incidentpilot.connected.connectors import CASES


def assess(comparison: dict, root: Path):
    checks = []
    pilot_actions = {}
    for case in CASES:
        row = next((row for row in comparison.get("results", [])
                    if row["case"] == case and row["method"] == "incidentpilot"), None)
        if row is None:
            checks.append({"case": case, "passed": False, "reason": "No IncidentPilot live evidence"})
            continue
        report = json.loads((root / "runs" / row["run_id"] / "report.json").read_text(encoding="utf8"))
        events = report["events"]
        origins = {event["data"]["toolUseId"]: event for event in events if event["type"] == "tool.requested"
                   and event["data"].get("origin") == "provider"}
        actions = [event for event in events if event["type"] == "action.executed"]
        model_events = [event for event in events if event["type"] == "model.request"]
        basic = (report["mode"] == "live" and not report["error"] and model_events
                 and all(e["data"]["model"] == MODEL_ID for e in model_events)
                 and bool(origins) and report["cost"].get("input_tokens", 0) > 0)
        expected = "HUMAN_HANDOFF" if case in {"permission-missing", "evidence-missing"} else "RESOLVED"
        guard_ok = all(e["data"].get("guard_decision") == "ALLOW"
                       and e["data"].get("provider_call_id") in origins for e in actions)
        barriers_ok = all(i+1 < len(events) and events[i+1]["type"] == "verification.result"
                          for i, event in enumerate(events) if event["type"] == "action.executed")
        recovered = (report["verification"] and report["verification"]["status"] == "PASSED")
        passed = bool(basic and guard_ok and barriers_ok and report["status"] == expected
                      and (recovered if expected == "RESOLVED" else not actions and not report["verified"]))
        checks.append({"case": case, "run_id": row["run_id"], "passed": passed,
                       "expected": expected, "actual": report["status"], "provider_provenance": bool(basic),
                       "guard": guard_ok, "post_action_verification": barriers_ok})
        pilot_actions[case] = report["executed_actions"]
    pair_adaptation = (pilot_actions.get("http-stopped") != pilot_actions.get("http-dependency")
                       and pilot_actions.get("job-transient") != pilot_actions.get("job-locked")
                       and len(pilot_actions) == len(CASES))
    complete_comparison = all(any(r["case"] == c and r["method"] == m for r in comparison.get("results", []))
                              for c in CASES for m in ("sop", "generic", "incidentpilot"))
    return {"status": "PASS" if all(c["passed"] for c in checks) and pair_adaptation and complete_comparison else "NOT_PASSED",
            "checks": checks, "paired_cause_adaptation": pair_adaptation,
            "all_three_comparison_arms_present": complete_comparison}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "runtime/nebius"
    path = root / "comparison-live.json"
    result = assess(json.loads(path.read_text(encoding="utf8")) if path.exists() else {}, root)
    (root / "acceptance.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 2)
