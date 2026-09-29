"""JSON-schema contract and strict local validation for Incident Memory."""

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
_MEMORY_REQUIRED = (
    "schema_version",
    "artifact_type",
    "memory_id",
    "generated_at",
    "run_id",
    "incident_id",
    "scenario_id",
    "title",
    "affected_service",
    "started_at",
    "completed_at",
    "final_status",
    "symptoms",
    "normalized_evidence",
    "confirmed_root_causes",
    "rejected_hypotheses",
    "actions",
    "resolution",
    "prevention_follow_up",
    "lookup_tokens",
    "evidence_event_ids",
)

_EVIDENCE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_EVIDENCE_REQUIRED),
    "properties": {
        "event_id": {"type": "string", "minLength": 1},
        "kind": {"enum": ["symptom", "root_cause", "rejected_hypothesis"]},
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

INCIDENT_MEMORY_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://incidentpilot.local/schemas/incident-memory-1.0.json",
    "title": "IncidentPilot Incident Memory",
    "type": "object",
    "additionalProperties": False,
    "required": list(_MEMORY_REQUIRED),
    "properties": {
        "schema_version": {"const": ARTIFACT_SCHEMA_VERSION},
        "artifact_type": {"const": "incident_memory"},
        "memory_id": {"type": "string", "minLength": 1},
        "generated_at": {"type": "string", "format": "date-time"},
        "run_id": {"type": "string", "minLength": 1},
        "incident_id": {"type": "string", "minLength": 1},
        "scenario_id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "affected_service": {"type": "string", "minLength": 1},
        "started_at": {"type": "string", "format": "date-time"},
        "completed_at": {"type": "string", "format": "date-time"},
        "final_status": {"enum": list(_FINAL_STATUSES)},
        "symptoms": {"type": "array", "minItems": 1, "items": _EVIDENCE_SCHEMA},
        "normalized_evidence": {
            "type": "array",
            "minItems": 1,
            "items": _EVIDENCE_SCHEMA,
        },
        "confirmed_root_causes": {
            "type": "array",
            "minItems": 1,
            "items": _EVIDENCE_SCHEMA,
        },
        "rejected_hypotheses": {"type": "array", "items": _EVIDENCE_SCHEMA},
        "actions": {"type": "array", "minItems": 1, "items": _ACTION_SCHEMA},
        "resolution": {
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
        "lookup_tokens": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
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


def _array(value: object, path: str, *, allow_empty: bool = False) -> list[object]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "an array" if allow_empty else "a non-empty array"
        raise ArtifactValidationError(f"{path} must be {qualifier}")
    return value


def _evidence(
    value: object,
    path: str,
    *,
    expected_kind: str | None,
    event_ids: set[str],
) -> tuple[object, ...]:
    evidence = _object(value, path, _EVIDENCE_REQUIRED)
    event_id = _text(evidence.get("event_id"), f"{path}.event_id")
    kind = evidence.get("kind")
    if kind not in {"symptom", "root_cause", "rejected_hypothesis"}:
        raise ArtifactValidationError(f"{path}.kind is invalid")
    if expected_kind is not None and kind != expected_kind:
        raise ArtifactValidationError(f"{path}.kind must be {expected_kind}")
    for field in ("code", "source", "summary"):
        _text(evidence.get(field), f"{path}.{field}")
    finding_id = evidence.get("finding_id")
    if finding_id is not None:
        _text(finding_id, f"{path}.finding_id")
    event_ids.add(event_id)
    return (
        evidence["event_id"],
        evidence["kind"],
        evidence["code"],
        evidence["source"],
        evidence["summary"],
        evidence["finding_id"],
    )


def _action(value: object, path: str, *, event_ids: set[str]) -> tuple[object, ...]:
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
    return tuple(action[field] for field in _ACTION_REQUIRED)


def validate_incident_memory(
    value: object,
    *,
    available_event_ids: Set[str] | None = None,
) -> Mapping[str, object]:
    """Validate exact shape, source links, and reusable-memory semantics."""

    memory = _object(value, "memory", _MEMORY_REQUIRED)
    if memory.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ArtifactValidationError("memory.schema_version is unsupported")
    if memory.get("artifact_type") != "incident_memory":
        raise ArtifactValidationError("memory.artifact_type must be incident_memory")
    for field in (
        "memory_id",
        "run_id",
        "incident_id",
        "scenario_id",
        "title",
        "affected_service",
    ):
        _text(memory.get(field), f"memory.{field}")
    _time(memory.get("generated_at"), "memory.generated_at")
    started = _time(memory.get("started_at"), "memory.started_at")
    completed = _time(memory.get("completed_at"), "memory.completed_at")
    if datetime.fromisoformat(completed.replace("Z", "+00:00")) < datetime.fromisoformat(
        started.replace("Z", "+00:00")
    ):
        raise ArtifactValidationError("memory.completed_at precedes started_at")
    final_status = memory.get("final_status")
    if final_status not in _FINAL_STATUSES:
        raise ArtifactValidationError("memory.final_status is invalid")

    referenced: set[str] = set()
    symptom_values = [
        _evidence(
            item,
            f"memory.symptoms[{index}]",
            expected_kind="symptom",
            event_ids=referenced,
        )
        for index, item in enumerate(_array(memory.get("symptoms"), "memory.symptoms"))
    ]
    root_values = [
        _evidence(
            item,
            f"memory.confirmed_root_causes[{index}]",
            expected_kind="root_cause",
            event_ids=referenced,
        )
        for index, item in enumerate(
            _array(
                memory.get("confirmed_root_causes"),
                "memory.confirmed_root_causes",
            )
        )
    ]
    rejected_values = [
        _evidence(
            item,
            f"memory.rejected_hypotheses[{index}]",
            expected_kind="rejected_hypothesis",
            event_ids=referenced,
        )
        for index, item in enumerate(
            _array(
                memory.get("rejected_hypotheses"),
                "memory.rejected_hypotheses",
                allow_empty=True,
            )
        )
    ]
    normalized_values = [
        _evidence(
            item,
            f"memory.normalized_evidence[{index}]",
            expected_kind=None,
            event_ids=referenced,
        )
        for index, item in enumerate(
            _array(memory.get("normalized_evidence"), "memory.normalized_evidence")
        )
    ]
    if normalized_values != [*symptom_values, *root_values, *rejected_values]:
        raise ArtifactValidationError(
            "memory.normalized_evidence must equal symptoms + roots + rejected hypotheses"
        )

    for index, action in enumerate(_array(memory.get("actions"), "memory.actions")):
        _action(action, f"memory.actions[{index}]", event_ids=referenced)

    resolution = _object(
        memory.get("resolution"),
        "memory.resolution",
        ("status", "summary", "verification_event_id", "verification_status"),
    )
    if resolution.get("status") != final_status:
        raise ArtifactValidationError("memory resolution status disagrees with final_status")
    _text(resolution.get("summary"), "memory.resolution.summary")
    verification_event_id = _text(
        resolution.get("verification_event_id"),
        "memory.resolution.verification_event_id",
    )
    referenced.add(verification_event_id)
    verification_status = resolution.get("verification_status")
    if verification_status not in {"passed", "failed"}:
        raise ArtifactValidationError("memory.resolution.verification_status is invalid")
    if final_status == "RESOLVED" and verification_status != "passed":
        raise ArtifactValidationError("RESOLVED memory requires passed verification")

    for index, note in enumerate(
        _array(memory.get("prevention_follow_up"), "memory.prevention_follow_up")
    ):
        _text(note, f"memory.prevention_follow_up[{index}]")
    token_values = _array(memory.get("lookup_tokens"), "memory.lookup_tokens")
    tokens = [_text(item, "memory.lookup_tokens item") for item in token_values]
    if len(tokens) != len(set(tokens)) or tokens != sorted(tokens):
        raise ArtifactValidationError("memory.lookup_tokens must be unique and sorted")
    if any(token != token.lower() for token in tokens):
        raise ArtifactValidationError("memory.lookup_tokens must be normalized lowercase")

    declared_values = _array(
        memory.get("evidence_event_ids"), "memory.evidence_event_ids"
    )
    declared = [_text(item, "memory.evidence_event_ids item") for item in declared_values]
    if len(declared) != len(set(declared)):
        raise ArtifactValidationError("memory.evidence_event_ids must be unique")
    if not referenced.issubset(set(declared)):
        raise ArtifactValidationError("memory contains undeclared evidence references")
    if available_event_ids is not None and not set(declared).issubset(set(available_event_ids)):
        raise ArtifactValidationError("memory references event IDs absent from the source trace")
    return memory
