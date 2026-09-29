"""Generate deterministic JSON and Markdown Incident Reports."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from html import escape

from incidentpilot.reporting.schema import validate_incident_report
from incidentpilot.reporting.source import ARTIFACT_SCHEMA_VERSION, IncidentFacts


def _generated_at(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("generated_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    return value.isoformat()


def build_incident_report(
    facts: IncidentFacts,
    *,
    generated_at: datetime,
) -> dict[str, object]:
    if not isinstance(facts, IncidentFacts):
        raise TypeError("facts must be IncidentFacts")
    if facts.final_verification_event_id is None or facts.final_verification_status is None:
        raise ValueError("report requires an authoritative verification event")
    report: dict[str, object] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_type": "incident_report",
        "report_id": f"REPORT-{facts.run_id}",
        "generated_at": _generated_at(generated_at),
        "run_id": facts.run_id,
        "incident_id": facts.incident_id,
        "scenario_id": facts.scenario_id,
        "title": facts.title,
        "incident_summary": facts.incident_summary,
        "affected_service": facts.affected_service,
        "started_at": facts.started_at,
        "completed_at": facts.completed_at,
        "final_status": facts.final_status,
        "symptoms": [item.as_dict() for item in facts.symptoms],
        "confirmed_root_causes": [
            item.as_dict() for item in facts.confirmed_root_causes
        ],
        "actions": [item.as_dict() for item in facts.actions],
        "outcome": {
            "status": facts.final_status,
            "summary": facts.resolution_summary,
            "verification_event_id": facts.final_verification_event_id,
            "verification_status": facts.final_verification_status,
        },
        "prevention_follow_up": list(facts.prevention_follow_up),
        "evidence_event_ids": list(facts.evidence_event_ids),
    }
    validate_incident_report(
        report,
        available_event_ids=set(facts.evidence_event_ids),
    )
    return report


def _cell(value: object) -> str:
    return escape(str(value), quote=False).replace("|", "\\|").replace("\n", " ")


def render_incident_report(report: Mapping[str, object]) -> str:
    validate_incident_report(report)
    symptoms = report["symptoms"]
    roots = report["confirmed_root_causes"]
    actions = report["actions"]
    outcome = report["outcome"]
    assert isinstance(symptoms, list)
    assert isinstance(roots, list)
    assert isinstance(actions, list)
    assert isinstance(outcome, Mapping)

    lines = [
        f"# {_cell(report['title'])}",
        "",
        f"- Report: `{_cell(report['report_id'])}`",
        f"- Run: `{_cell(report['run_id'])}`",
        f"- Incident: `{_cell(report['incident_id'])}`",
        f"- Scenario: `{_cell(report['scenario_id'])}`",
        f"- Service: `{_cell(report['affected_service'])}`",
        f"- Status: **{_cell(report['final_status'])}**",
        f"- Window: {_cell(report['started_at'])} to {_cell(report['completed_at'])}",
        "",
        "## Incident summary",
        "",
        _cell(report["incident_summary"]),
        "",
        "## Symptoms",
        "",
    ]
    for item in symptoms:
        assert isinstance(item, Mapping)
        lines.append(
            f"- `{_cell(item['code'])}` — {_cell(item['summary'])} "
            f"(evidence `{_cell(item['event_id'])}`)"
        )
    lines.extend(["", "## Confirmed root causes", ""])
    for item in roots:
        assert isinstance(item, Mapping)
        lines.append(
            f"- `{_cell(item['code'])}` — {_cell(item['summary'])} "
            f"(evidence `{_cell(item['event_id'])}`)"
        )
    lines.extend(
        [
            "",
            "## Recovery and authoritative verification",
            "",
            "| Action | Target | Outcome | Policy | Verification | Evidence |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in actions:
        assert isinstance(item, Mapping)
        evidence = ", ".join(
            f"`{_cell(item[field])}`"
            for field in (
                "request_event_id",
                "policy_event_id",
                "action_event_id",
                "verification_event_id",
                "result_event_id",
            )
        )
        lines.append(
            f"| `{_cell(item['action'])}` | `{_cell(item['target'])}` | "
            f"{_cell(item['outcome'])} | {_cell(item['policy_decision'])} "
            f"({_cell(item['risk'])}) | {_cell(item['verification_status'])} | {evidence} |"
        )
    lines.extend(
        [
            "",
            "## Outcome",
            "",
            _cell(outcome["summary"]),
            "",
            (
                f"Authoritative verification: **{_cell(outcome['verification_status'])}** "
                f"at `{_cell(outcome['verification_event_id'])}`."
            ),
            "",
            "## Prevention and follow-up",
            "",
        ]
    )
    follow_up = report["prevention_follow_up"]
    assert isinstance(follow_up, list)
    lines.extend(f"- {_cell(note)}" for note in follow_up)
    lines.extend(["", "## Evidence index", ""])
    evidence_ids = report["evidence_event_ids"]
    assert isinstance(evidence_ids, list)
    lines.append(", ".join(f"`{_cell(event_id)}`" for event_id in evidence_ids))
    return "\n".join(lines) + "\n"
