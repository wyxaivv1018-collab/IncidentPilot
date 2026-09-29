"""JSON-schema contract and strict local validation for Incident Reports."""

from __future__ import annotations

from collections.abc import Mapping, Set
from datetime import datetime

from incidentpilot.reporting.source import (
    ARTIFACT_SCHEMA_VERSION,
    ArtifactValidationError,
)

_FINAL_STATUSES = (
    "RESOLVED",
    "UNRESOLVED",
    "FAILED",
    "TIMEOUT",
    "BUDGET_EXCEEDED",
    "AUTH_BLOCKED",
    "RUNTIME_BLOCKED",
)
_EVIDENCE_REQUIRED = (
    "event_id",
    "kind",
    "code",
    "source",
    "summary",
    "finding_id",
)
_ACTION_REQUIRED = (
    "request_event_id",
    "policy_event_id",
    "action_event_id",
    "verification_event_id",
    "result_event_id",
    "action",
    "target",
    "outcome",
    "detail",
    "risk",
    "policy_decision",
    "approval_required",
    "approval_id",
    "verification_status",
    "verification_detail",
)
_REPORT_REQUIRED = (
    "schema_version",
    "artifact_type",
    "report_id",
    "generated_at",
    "run_id",
    "incident_id",
    "scenario_id",
    "title",
    "incident_summary",
    "affected_service",
    "started_at",
    "completed_at",
    "final_status",
    "symptoms",
    "confirmed_root_causes",
    "actions",
    "outcome",
    "prevention_follow_up",
    "evidence_event_ids",
)

_EVIDENCE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_EVIDENCE_REQUIRED),
    "properties": {
        "event_id": {"type": "string", "minLength": 1},
        "kind": {"enum": ["symptom", "root_cause"]},
        "code": {"type": "string", "minLength": 1},
        "source": {"type": "string", "minLength": 1},
        "summary": {"type": "string", "minLength": 1},
        "finding_id": {"type": ["string", "null"]},
    },
}
_ACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_ACTION_REQUIRED),
    "properties": {
        **{
            field: {"type": "string", "minLength": 1}
            for field in _ACTION_REQUIRED
            if field not in {"approval_required", "approval_id"}
        },
        "approval_required": {"type": "boolean"},
        "approval_id": {"type": ["string", "null"]},
        "verification_status": {"enum": ["passed", "failed"]},
    },
}

INCIDENT_REPORT_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://incidentpilot.local/schemas/incident-report-1.0.json",
    "title": "IncidentPilot Incident Report",
    "type": "object",
    "additionalProperties": False,
    "required": list(_REPORT_REQUIRED),
    "properties": {
        "schema_version": {"const": ARTIFACT_SCHEMA_VERSION},
        "artifact_type": {"const": "incident_report"},
        "report_id": {"type": "string", "minLength": 1},
        "generated_at": {"type": "string", "format": "date-time"},
        "run_id": {"type": "string", "minLength": 1},
        "incident_id": {"type": "string", "minLength": 1},
        "scenario_id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "incident_summary": {"type": "string", "minLength": 1},
        "affected_service": {"type": "string", "minLength": 1},
        "started_at": {"type": "string", "format": "date-time"},
        "completed_at": {"type": "string", "format": "date-time"},
        "final_status": {"enum": list(_FINAL_STATUSES)},
        "symptoms": {"type": "array", "minItems": 1, "items": _EVIDENCE_SCHEMA},
        "confirmed_root_causes": {
            "type": "array",
            "minItems": 1,
            "items": _EVIDENCE_SCHEMA,
        },
        "actions": {"type": "array", "minItems": 1, "items": _ACTION_SCHEMA},
        "outcome": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "status",
                "summary",
                "verification_event_id",
                "verification_status",
            ],
            "properties": {
                "status": {"enum": list(_FINAL_STATUSES)},
                "summary": {"type": "string", "minLength": 1},
                "verification_event_id": {"type": "string", "minLength": 1},
                "verification_status": {"enum": ["passed", "failed"]},
            },
        },
        "prevention_follow_up": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "evidence_event_ids": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
    },
}


def _object(value: object, path: str, required: tuple[str, ...]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ArtifactValidationError(f"{path} must be an object")
    keys = set(value)
    expected = set(required)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ArtifactValidationError(f"{path} keys invalid; missing={missing}, extra={extra}")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactValidationError(f"{path} must be a non-empty string")
    return value


def _time(value: object, path: str) -> str:
    text = _text(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArtifactValidationError(f"{path} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ArtifactValidationError(f"{path} must include a timezone")
    return text


def _array(value: object, path: str) -> list[object]:
    if not isinstance(value, list) or not value:
        raise ArtifactValidationError(f"{path} must be a non-empty array")
    return value


def _evidence(
    value: object,
    path: str,
    *,
    expected_kind: str,
    event_ids: set[str],
) -> None:
    evidence = _object(value, path, _EVIDENCE_REQUIRED)
    event_id = _text(evidence.get("event_id"), f"{path}.event_id")
    if evidence.get("kind") != expected_kind:
        raise ArtifactValidationError(f"{path}.kind must be {expected_kind}")
    for field in ("code", "source", "summary"):
        _text(evidence.get(field), f"{path}.{field}")
    finding_id = evidence.get("finding_id")
    if finding_id is not None:
        _text(finding_id, f"{path}.finding_id")
    event_ids.add(event_id)


def _action(value: object, path: str, *, event_ids: set[str]) -> None:
    action = _object(value, path, _ACTION_REQUIRED)
    for field in _ACTION_REQUIRED:
        if field in {"approval_required", "approval_id"}:
            continue
        _text(action.get(field), f"{path}.{field}")
    if action.get("policy_decision") != "ALLOW":
        raise ArtifactValidationError(f"{path}.policy_decision must be ALLOW")
    if action.get("verification_status") not in {"passed", "failed"}:
        raise ArtifactValidationError(f"{path}.verification_status is invalid")
    approval_required = action.get("approval_required")
    if not isinstance(approval_required, bool):
        raise ArtifactValidationError(f"{path}.approval_required must be boolean")
    approval_id = action.get("approval_id")
    if approval_id is not None:
        _text(approval_id, f"{path}.approval_id")
    if approval_required and approval_id is None:
        raise ArtifactValidationError(f"{path} requires an approval_id")
    for field in (
        "request_event_id",
        "policy_event_id",
        "action_event_id",
        "verification_event_id",
        "result_event_id",
    ):
        event_ids.add(str(action[field]))


def validate_incident_report(
    value: object,
    *,
    available_event_ids: Set[str] | None = None,
) -> Mapping[str, object]:
    """Validate exact shape, evidence links, and resolution semantics."""

    report = _object(value, "report", _REPORT_REQUIRED)
    if report.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ArtifactValidationError("report.schema_version is unsupported")
    if report.get("artifact_type") != "incident_report":
        raise ArtifactValidationError("report.artifact_type must be incident_report")
    for field in (
        "report_id",
        "run_id",
        "incident_id",
        "scenario_id",
        "title",
        "incident_summary",
        "affected_service",
    ):
        _text(report.get(field), f"report.{field}")
    _time(report.get("generated_at"), "report.generated_at")
    started = _time(report.get("started_at"), "report.started_at")
    completed = _time(report.get("completed_at"), "report.completed_at")
    if datetime.fromisoformat(completed.replace("Z", "+00:00")) < datetime.fromisoformat(
        started.replace("Z", "+00:00")
    ):
        raise ArtifactValidationError("report.completed_at precedes started_at")
    final_status = report.get("final_status")
    if final_status not in _FINAL_STATUSES:
        raise ArtifactValidationError("report.final_status is invalid")

    referenced: set[str] = set()
    for index, evidence in enumerate(_array(report.get("symptoms"), "report.symptoms")):
        _evidence(
            evidence,
            f"report.symptoms[{index}]",
            expected_kind="symptom",
            event_ids=referenced,
        )
    for index, evidence in enumerate(
        _array(report.get("confirmed_root_causes"), "report.confirmed_root_causes")
    ):
        _evidence(
            evidence,
            f"report.confirmed_root_causes[{index}]",
            expected_kind="root_cause",
            event_ids=referenced,
        )
    for index, action in enumerate(_array(report.get("actions"), "report.actions")):
        _action(action, f"report.actions[{index}]", event_ids=referenced)

    outcome = _object(
        report.get("outcome"),
        "report.outcome",
        ("status", "summary", "verification_event_id", "verification_status"),
    )
    if outcome.get("status") != final_status:
        raise ArtifactValidationError("report outcome status disagrees with final_status")
    _text(outcome.get("summary"), "report.outcome.summary")
    verification_event_id = _text(
        outcome.get("verification_event_id"), "report.outcome.verification_event_id"
    )
    referenced.add(verification_event_id)
    verification_status = outcome.get("verification_status")
    if verification_status not in {"passed", "failed"}:
        raise ArtifactValidationError("report.outcome.verification_status is invalid")
    if final_status == "RESOLVED" and verification_status != "passed":
        raise ArtifactValidationError("RESOLVED report requires passed verification")

    for index, note in enumerate(
        _array(report.get("prevention_follow_up"), "report.prevention_follow_up")
    ):
        _text(note, f"report.prevention_follow_up[{index}]")
    declared_values = _array(
        report.get("evidence_event_ids"), "report.evidence_event_ids"
    )
    declared = [_text(item, "report.evidence_event_ids item") for item in declared_values]
    if len(declared) != len(set(declared)):
        raise ArtifactValidationError("report.evidence_event_ids must be unique")
    if not referenced.issubset(set(declared)):
        raise ArtifactValidationError("report contains undeclared evidence references")
    if available_event_ids is not None and not set(declared).issubset(set(available_event_ids)):
        raise ArtifactValidationError("report references event IDs absent from the source trace")
    return report
