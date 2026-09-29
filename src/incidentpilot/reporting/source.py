"""Strict C07 extraction of reportable facts from a completed IncidentPilot trace."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from incidentpilot.agent.redaction import REDACTED, redact_json_value

ARTIFACT_SCHEMA_VERSION = "1.0"

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TERMINAL_EVENT_TYPES = {
    "run.completed",
    "run.failed",
    "run.timeout",
    "run.budget_exceeded",
}
_FINAL_STATUSES = {
    "RESOLVED",
    "UNRESOLVED",
    "FAILED",
    "TIMEOUT",
    "BUDGET_EXCEEDED",
    "AUTH_BLOCKED",
    "RUNTIME_BLOCKED",
}


class ArtifactSourceError(ValueError):
    """Raised when a source trace cannot safely support final artifacts."""


class ArtifactValidationError(ValueError):
    """Raised when a generated or loaded artifact violates its contract."""


@dataclass(frozen=True, slots=True)
class EvidenceFact:
    event_id: str
    kind: str
    code: str
    source: str
    summary: str
    finding_id: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "code": self.code,
            "source": self.source,
            "summary": self.summary,
            "finding_id": self.finding_id,
        }


@dataclass(frozen=True, slots=True)
class ActionFact:
    request_event_id: str
    policy_event_id: str
    action_event_id: str
    verification_event_id: str
    result_event_id: str
    action: str
    target: str
    outcome: str
    detail: str
    risk: str
    policy_decision: str
    approval_required: bool
    approval_id: str | None
    verification_status: str
    verification_detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "request_event_id": self.request_event_id,
            "policy_event_id": self.policy_event_id,
            "action_event_id": self.action_event_id,
            "verification_event_id": self.verification_event_id,
            "result_event_id": self.result_event_id,
            "action": self.action,
            "target": self.target,
            "outcome": self.outcome,
            "detail": self.detail,
            "risk": self.risk,
            "policy_decision": self.policy_decision,
            "approval_required": self.approval_required,
            "approval_id": self.approval_id,
            "verification_status": self.verification_status,
            "verification_detail": self.verification_detail,
        }


@dataclass(frozen=True, slots=True)
class IncidentFacts:
    run_id: str
    incident_id: str
    scenario_id: str
    title: str
    incident_summary: str
    affected_service: str
    started_at: str
    completed_at: str
    final_status: str
    symptoms: tuple[EvidenceFact, ...]
    confirmed_root_causes: tuple[EvidenceFact, ...]
    rejected_hypotheses: tuple[EvidenceFact, ...]
    actions: tuple[ActionFact, ...]
    final_verification_event_id: str | None
    final_verification_status: str | None
    resolution_summary: str
    prevention_follow_up: tuple[str, ...]
    evidence_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _TraceIndex:
    source: Mapping[str, object]
    run_id: str
    events: tuple[Mapping[str, object], ...]
    by_id: Mapping[str, Mapping[str, object]]
    positions: Mapping[str, int]


def _normalize_key(value: str) -> str:
    return value.lower().replace("-", "_")


def _redact_configured(
    value: object,
    *,
    secret_fields: frozenset[str],
    key: str | None = None,
) -> object:
    if key is not None and _normalize_key(key) in secret_fields:
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact_configured(
                item,
                secret_fields=secret_fields,
                key=str(item_key),
            )
            for item_key, item in value.items()
        }
    if isinstance(value, list) or isinstance(value, tuple):
        return [
            _redact_configured(item, secret_fields=secret_fields)
            for item in value
        ]
    return value


def _redact_source(
    source: Mapping[str, object],
    secret_fields: Sequence[str],
) -> Mapping[str, object]:
    normalized_fields: set[str] = set()
    for field_name in secret_fields:
        if not isinstance(field_name, str) or not field_name.strip():
            raise ArtifactSourceError("secret field names must be non-empty strings")
        normalized_fields.add(_normalize_key(field_name.strip()))
    default_redacted = redact_json_value(source)
    configured_redacted = _redact_configured(
        default_redacted,
        secret_fields=frozenset(normalized_fields),
    )
    if not isinstance(configured_redacted, Mapping):
        raise ArtifactSourceError("redacted trace must remain a JSON object")
    return configured_redacted


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ArtifactSourceError(f"{path} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ArtifactSourceError(f"{path} keys must be strings")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ArtifactSourceError(f"{path} must be an array")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactSourceError(f"{path} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    return _string(value, path)


def _identifier(value: object, path: str) -> str:
    identifier = _string(value, path)
    if _SAFE_IDENTIFIER.fullmatch(identifier) is None:
        raise ArtifactSourceError(f"{path} is not a safe identifier")
    return identifier


def _timestamp(value: object, path: str) -> tuple[str, datetime]:
    text = _string(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArtifactSourceError(f"{path} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ArtifactSourceError(f"{path} must include a timezone")
    return text, parsed


def _event_payload(event: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(event.get("payload"), f"event {event.get('event_id')} payload")


def _build_index(
    source: Mapping[str, object],
    *,
    secret_fields: Sequence[str],
) -> _TraceIndex:
    redacted = _redact_source(source, secret_fields)
    _string(redacted.get("schema_version"), "schema_version")
    run_id = _identifier(redacted.get("run_id"), "run_id")
    trace = _mapping(redacted.get("trace"), "trace")
    event_values = _list(trace.get("events"), "trace.events")
    if not event_values:
        raise ArtifactSourceError("trace.events must not be empty")
    if len(event_values) > 10_000:
        raise ArtifactSourceError("trace.events exceeds the local artifact limit")

    events: list[Mapping[str, object]] = []
    by_id: dict[str, Mapping[str, object]] = {}
    positions: dict[str, int] = {}
    previous_time: datetime | None = None
    for position, raw_event in enumerate(event_values, start=1):
        event = _mapping(raw_event, f"trace.events[{position - 1}]")
        event_id = _identifier(event.get("event_id"), f"event {position} event_id")
        if event_id in by_id:
            raise ArtifactSourceError(f"duplicate event_id: {event_id}")
        if event.get("run_id") != run_id:
            raise ArtifactSourceError(f"event {event_id} run_id does not match the trace")
        if event.get("sequence") != position:
            raise ArtifactSourceError(f"event {event_id} sequence is not contiguous")
        _string(event.get("event_type"), f"event {event_id} event_type")
        _string(event.get("schema_version"), f"event {event_id} schema_version")
        _string(event.get("summary"), f"event {event_id} summary")
        _, occurred_at = _timestamp(
            event.get("occurred_at"), f"event {event_id} occurred_at"
        )
        if previous_time is not None and occurred_at < previous_time:
            raise ArtifactSourceError("trace event timestamps must be non-decreasing")
        previous_time = occurred_at
        _event_payload(event)
        related = _list(
            event.get("related_event_ids"),
            f"event {event_id} related_event_ids",
        )
        for related_id_value in related:
            related_id = _identifier(
                related_id_value,
                f"event {event_id} related_event_id",
            )
            if related_id not in by_id:
                raise ArtifactSourceError(
                    f"event {event_id} references missing or future event {related_id}"
                )
        events.append(event)
        by_id[event_id] = event
        positions[event_id] = position

    if events[0].get("event_type") != "run.started":
        raise ArtifactSourceError("the first event must be run.started")
    if events[-1].get("event_type") not in _TERMINAL_EVENT_TYPES:
        raise ArtifactSourceError("the final event must be a terminal run event")
    return _TraceIndex(
        source=redacted,
        run_id=run_id,
        events=tuple(events),
        by_id=by_id,
        positions=positions,
    )


def _tool_pairs(
    index: _TraceIndex,
    tool_name: str,
) -> tuple[tuple[Mapping[str, object], Mapping[str, object]], ...]:
    requests: dict[str, Mapping[str, object]] = {}
    results: dict[str, Mapping[str, object]] = {}
    for event in index.events:
        event_type = event.get("event_type")
        tool_call_id = event.get("tool_call_id")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            continue
        if event_type == "tool.requested":
            payload = _event_payload(event)
            if payload.get("tool_name") == tool_name:
                requests[tool_call_id] = event
        elif event_type == "tool.result":
            results[tool_call_id] = event
    pairs: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    for call_id, request in requests.items():
        result = results.get(call_id)
        if result is None:
            raise ArtifactSourceError(f"tool request {call_id} has no typed result")
        pairs.append((request, result))
    return tuple(pairs)


def _finding(
    value: object,
    *,
    event_id: str,
    kind: str,
    incident_id: str,
) -> EvidenceFact:
    finding = _mapping(value, f"event {event_id} finding")
    if finding.get("incident_id") != incident_id:
        raise ArtifactSourceError(f"event {event_id} finding belongs to another incident")
    return EvidenceFact(
        event_id=event_id,
        kind=kind,
        code=_string(finding.get("code"), f"event {event_id} finding code"),
        source=_string(finding.get("source"), f"event {event_id} finding source"),
        summary=_string(finding.get("message"), f"event {event_id} finding message"),
        finding_id=_identifier(
            finding.get("finding_id"), f"event {event_id} finding_id"
        ),
    )


def _deduplicate_evidence(values: Sequence[EvidenceFact]) -> tuple[EvidenceFact, ...]:
    seen: set[tuple[str, str | None]] = set()
    result: list[EvidenceFact] = []
    for value in values:
        key = (value.code, value.finding_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def _incident_data(index: _TraceIndex) -> tuple[Mapping[str, object], str]:
    pairs = _tool_pairs(index, "read_incident")
    if not pairs:
        raise ArtifactSourceError("trace has no read_incident observation")
    _, result = pairs[0]
    payload = _event_payload(result)
    if payload.get("status") != "completed":
        raise ArtifactSourceError("read_incident did not complete")
    return _mapping(payload.get("data"), "read_incident data"), _string(
        result.get("event_id"), "read_incident result event_id"
    )


def _initial_environment(
    index: _TraceIndex,
    *,
    first_action_position: int,
) -> tuple[Mapping[str, object], str]:
    for _, result in _tool_pairs(index, "read_environment"):
        event_id = _string(result.get("event_id"), "environment result event_id")
        if index.positions[event_id] >= first_action_position:
            continue
        payload = _event_payload(result)
        if payload.get("status") != "completed":
            continue
        return _mapping(payload.get("data"), "read_environment data"), event_id
    raise ArtifactSourceError("trace has no pre-action environment observation")


def _symptoms(
    index: _TraceIndex,
    *,
    incident_id: str,
    first_action_position: int,
) -> tuple[EvidenceFact, ...]:
    values: list[EvidenceFact] = []
    for _, result in _tool_pairs(index, "read_logs"):
        event_id = _string(result.get("event_id"), "logs result event_id")
        if index.positions[event_id] >= first_action_position:
            continue
        payload = _event_payload(result)
        if payload.get("status") != "completed":
            continue
        for finding in _list(payload.get("data"), f"event {event_id} log data"):
            values.append(
                _finding(
                    finding,
                    event_id=event_id,
                    kind="symptom",
                    incident_id=incident_id,
                )
            )
    if not values:
        raise ArtifactSourceError("trace has no pre-action symptom evidence")
    return _deduplicate_evidence(values)


def _action_result_events(
    index: _TraceIndex,
) -> Mapping[str, Mapping[str, object]]:
    results: dict[str, Mapping[str, object]] = {}
    for event in index.events:
        if event.get("event_type") != "tool.result":
            continue
        action_event_id = _event_payload(event).get("action_event_id")
        if isinstance(action_event_id, str):
            if action_event_id in results:
                raise ArtifactSourceError(
                    f"action {action_event_id} has multiple typed results"
                )
            results[action_event_id] = event
    return results


def _verification_events(
    index: _TraceIndex,
) -> Mapping[str, Mapping[str, object]]:
    results: dict[str, Mapping[str, object]] = {}
    for event in index.events:
        if event.get("event_type") != "verification.result":
            continue
        action_event_id = _event_payload(event).get("verified_action_event_id")
        if not isinstance(action_event_id, str):
            raise ArtifactSourceError("verification.result is not bound to an action event")
        if action_event_id in results:
            raise ArtifactSourceError(
                f"action {action_event_id} has multiple authoritative verifications"
            )
        results[action_event_id] = event
    return results


def _tool_call_id(event: Mapping[str, object], path: str) -> str:
    return _identifier(event.get("tool_call_id"), f"{path} tool_call_id")


def _related_event_ids(event: Mapping[str, object], path: str) -> tuple[str, ...]:
    return tuple(
        _identifier(value, f"{path} related_event_id")
        for value in _list(event.get("related_event_ids"), f"{path} related_event_ids")
    )


def _require_related_events(
    event: Mapping[str, object],
    required_event_ids: Sequence[str],
    path: str,
) -> None:
    related = set(_related_event_ids(event, path))
    missing = set(required_event_ids) - related
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ArtifactSourceError(f"{path} is missing related events: {missing_text}")


def _actions_and_new_causes(
    index: _TraceIndex,
    *,
    incident_id: str,
) -> tuple[tuple[ActionFact, ...], tuple[EvidenceFact, ...]]:
    result_events = _action_result_events(index)
    verification_events = _verification_events(index)
    action_events = tuple(
        event for event in index.events if event.get("event_type") == "action.executed"
    )
    action_event_ids = {
        _string(event.get("event_id"), "action event_id") for event in action_events
    }
    if set(result_events) != action_event_ids:
        raise ArtifactSourceError(
            "typed action results do not exactly cover the executed actions"
        )
    if set(verification_events) != action_event_ids:
        raise ArtifactSourceError(
            "authoritative verifications do not exactly cover the executed actions"
        )

    actions: list[ActionFact] = []
    new_causes: list[EvidenceFact] = []
    seen_tool_call_ids: set[str] = set()

    for action_event in action_events:
        action_event_id = _string(action_event.get("event_id"), "action event_id")
        action_tool_call_id = _tool_call_id(
            action_event, f"action {action_event_id}"
        )
        if action_tool_call_id in seen_tool_call_ids:
            raise ArtifactSourceError(
                f"tool call {action_tool_call_id} executed multiple actions"
            )
        seen_tool_call_ids.add(action_tool_call_id)
        payload = _event_payload(action_event)
        if payload.get("executed") is not True or payload.get("action_result_valid") is not True:
            raise ArtifactSourceError(f"action {action_event_id} was not validly executed")
        if payload.get("incident_resolved") is not False:
            raise ArtifactSourceError(
                f"action {action_event_id} improperly claims incident resolution"
            )
        action_result = _mapping(
            payload.get("action_result"), f"action {action_event_id} result"
        )
        request = _mapping(
            action_result.get("request"), f"action {action_event_id} request"
        )
        if request.get("incident_id") != incident_id:
            raise ArtifactSourceError(f"action {action_event_id} belongs to another incident")
        action_name = _string(request.get("action"), f"action {action_event_id} name")
        target = _string(request.get("target"), f"action {action_event_id} target")
        outcome = _string(action_result.get("outcome"), f"action {action_event_id} outcome")
        detail = _string(action_result.get("detail"), f"action {action_event_id} detail")
        if payload.get("operation_outcome") != outcome:
            raise ArtifactSourceError(
                f"action {action_event_id} operation outcome disagrees with its result"
            )

        action_related_ids = _related_event_ids(
            action_event, f"action {action_event_id}"
        )
        request_events = tuple(
            index.by_id[related_id]
            for related_id in action_related_ids
            if index.by_id[related_id].get("event_type") == "tool.requested"
        )
        if len(request_events) != 1:
            raise ArtifactSourceError(
                f"action {action_event_id} must have exactly one provider request event"
            )
        request_event = request_events[0]
        request_event_id = _string(request_event.get("event_id"), "request event_id")
        if _tool_call_id(request_event, f"request {request_event_id}") != action_tool_call_id:
            raise ArtifactSourceError(
                f"action {action_event_id} provider request tool_call_id disagrees"
            )
        request_payload = _event_payload(request_event)
        if request_payload.get("tool_name") != action_name:
            raise ArtifactSourceError(
                f"action {action_event_id} does not match its provider tool request"
            )
        request_arguments = _mapping(
            request_payload.get("arguments"),
            f"request {request_event_id} arguments",
        )
        if request_arguments.get("target") != target:
            raise ArtifactSourceError(
                f"action {action_event_id} target disagrees with provider arguments"
            )
        request_incident_id = request_arguments.get("incident_id")
        if request_incident_id is not None and request_incident_id != incident_id:
            raise ArtifactSourceError(
                f"action {action_event_id} incident disagrees with provider arguments"
            )

        policy_event_id = _identifier(
            payload.get("policy_event_id"), f"action {action_event_id} policy_event_id"
        )
        policy_event = index.by_id.get(policy_event_id)
        if policy_event is None or policy_event.get("event_type") != "policy.decision":
            raise ArtifactSourceError(f"action {action_event_id} has no valid policy event")
        if _tool_call_id(policy_event, f"policy {policy_event_id}") != action_tool_call_id:
            raise ArtifactSourceError(
                f"action {action_event_id} policy tool_call_id disagrees"
            )
        _require_related_events(
            policy_event,
            (request_event_id,),
            f"policy {policy_event_id}",
        )
        _require_related_events(
            action_event,
            (request_event_id, policy_event_id),
            f"action {action_event_id}",
        )
        policy_payload = _event_payload(policy_event)
        policy_decision = _string(
            policy_payload.get("decision"), f"policy {policy_event_id} decision"
        )
        if policy_decision != "ALLOW" or policy_payload.get("executed") is not True:
            raise ArtifactSourceError(
                f"executed action {action_event_id} was not allowed by policy"
            )
        risk = _string(policy_payload.get("risk"), f"policy {policy_event_id} risk")
        approval_id = _optional_string(
            policy_payload.get("approval_id"), f"policy {policy_event_id} approval_id"
        )

        verification_event = verification_events.get(action_event_id)
        result_event = result_events.get(action_event_id)
        if verification_event is None or result_event is None:
            raise ArtifactSourceError(
                f"action {action_event_id} lacks authoritative verification or typed result"
            )
        verification_event_id = _string(
            verification_event.get("event_id"), "verification event_id"
        )
        result_event_id = _string(result_event.get("event_id"), "result event_id")
        for chain_event, chain_name in (
            (verification_event, f"verification {verification_event_id}"),
            (result_event, f"tool result {result_event_id}"),
        ):
            if _tool_call_id(chain_event, chain_name) != action_tool_call_id:
                raise ArtifactSourceError(
                    f"action {action_event_id} {chain_name} tool_call_id disagrees"
                )
        verification_payload = _event_payload(verification_event)
        if verification_payload.get("verified_action_event_id") != action_event_id:
            raise ArtifactSourceError(
                f"verification {verification_event_id} is bound to another action"
            )
        if verification_payload.get("verification_trigger") != "post_action_barrier":
            raise ArtifactSourceError(
                f"verification {verification_event_id} is not a post_action_barrier"
            )
        barrier_event_id = _identifier(
            verification_payload.get("barrier_started_event_id"),
            f"verification {verification_event_id} barrier_started_event_id",
        )
        barrier_event = index.by_id.get(barrier_event_id)
        if (
            barrier_event is None
            or barrier_event.get("event_type")
            != "post_action_verification.started"
        ):
            raise ArtifactSourceError(
                f"verification {verification_event_id} has no valid barrier-start event"
            )
        if _tool_call_id(barrier_event, f"barrier {barrier_event_id}") != action_tool_call_id:
            raise ArtifactSourceError(
                f"action {action_event_id} barrier tool_call_id disagrees"
            )
        barrier_payload = _event_payload(barrier_event)
        if (
            barrier_payload.get("verification_trigger") != "post_action_barrier"
            or barrier_payload.get("verified_action_event_id") != action_event_id
        ):
            raise ArtifactSourceError(
                f"barrier {barrier_event_id} is not bound to action {action_event_id}"
            )
        verification = _mapping(
            verification_payload.get("verification"),
            f"verification {verification_event_id} body",
        )
        verification_status = _string(
            verification_payload.get("status"),
            f"verification {verification_event_id} status",
        )
        if verification.get("status") != verification_status:
            raise ArtifactSourceError(
                f"verification {verification_event_id} status fields disagree"
            )
        verification_detail = _string(
            verification.get("detail"),
            f"verification {verification_event_id} detail",
        )
        if verification.get("incident_id") != incident_id:
            raise ArtifactSourceError(
                f"verification {verification_event_id} belongs to another incident"
            )
        result_payload = _event_payload(result_event)
        if (
            result_payload.get("status") != "completed"
            or result_payload.get("executed") is not True
            or result_payload.get("operation_outcome") != outcome
            or result_payload.get("policy_event_id") != policy_event_id
        ):
            raise ArtifactSourceError(
                f"tool result {result_event_id} disagrees with the executed action"
            )
        typed_action_result = _mapping(
            result_payload.get("action_result"),
            f"tool result {result_event_id} action_result",
        )
        if dict(typed_action_result) != dict(action_result):
            raise ArtifactSourceError(
                f"tool result {result_event_id} action_result differs from execution"
            )
        if result_payload.get("action_result_establishes_resolution") is not False:
            raise ArtifactSourceError(
                f"tool result {result_event_id} treats action success as resolution"
            )
        post_action = _mapping(
            result_payload.get("post_action_verification"),
            f"tool result {result_event_id} post_action_verification",
        )
        if (
            post_action.get("verification_event_id") != verification_event_id
            or post_action.get("verification_status") != verification_status
            or post_action.get("verification_trigger") != "post_action_barrier"
            or post_action.get("verified_action_event_id") != action_event_id
            or post_action.get("barrier_started_event_id") != barrier_event_id
        ):
            raise ArtifactSourceError(
                f"tool result {result_event_id} disagrees with authoritative verification"
            )
        post_action_verification = _mapping(
            post_action.get("verification"),
            f"tool result {result_event_id} verification body",
        )
        if dict(post_action_verification) != dict(verification):
            raise ArtifactSourceError(
                f"tool result {result_event_id} verification body differs from authority"
            )
        expected_resolved = verification_status == "passed"
        if post_action.get("incident_resolved") is not expected_resolved:
            raise ArtifactSourceError(
                f"tool result {result_event_id} incident resolution flag disagrees"
            )

        observation_event_id = _identifier(
            post_action.get("observation_event_id"),
            f"tool result {result_event_id} observation_event_id",
        )
        observation_event = index.by_id.get(observation_event_id)
        if (
            observation_event is None
            or observation_event.get("event_type")
            != "verification.observation_delivered"
        ):
            raise ArtifactSourceError(
                f"tool result {result_event_id} has no valid observation delivery"
            )
        if (
            _tool_call_id(observation_event, f"observation {observation_event_id}")
            != action_tool_call_id
        ):
            raise ArtifactSourceError(
                f"action {action_event_id} observation tool_call_id disagrees"
            )
        observation_payload = _event_payload(observation_event)
        if (
            observation_payload.get("delivery_channel") != "action_tool_result"
            or observation_payload.get("status") != verification_status
            or observation_payload.get("verification_event_id")
            != verification_event_id
            or observation_payload.get("verification_trigger")
            != "post_action_barrier"
            or observation_payload.get("verified_action_event_id") != action_event_id
        ):
            raise ArtifactSourceError(
                f"observation {observation_event_id} disagrees with verification"
            )

        _require_related_events(
            barrier_event,
            (action_event_id,),
            f"barrier {barrier_event_id}",
        )
        _require_related_events(
            verification_event,
            (request_event_id, action_event_id, barrier_event_id),
            f"verification {verification_event_id}",
        )
        _require_related_events(
            observation_event,
            (action_event_id, verification_event_id),
            f"observation {observation_event_id}",
        )
        _require_related_events(
            result_event,
            (
                request_event_id,
                policy_event_id,
                action_event_id,
                barrier_event_id,
                verification_event_id,
                observation_event_id,
            ),
            f"tool result {result_event_id}",
        )

        chain_event_ids = (
            request_event_id,
            policy_event_id,
            action_event_id,
            barrier_event_id,
            verification_event_id,
            observation_event_id,
            result_event_id,
        )
        chain_positions = tuple(index.positions[event_id] for event_id in chain_event_ids)
        if chain_positions != tuple(sorted(chain_positions)) or len(
            set(chain_positions)
        ) != len(chain_positions):
            raise ArtifactSourceError(
                f"action {action_event_id} synchronous provenance ordering is invalid"
            )
        if any(
            other_event.get("event_id") != action_event_id
            and index.positions[_string(other_event.get("event_id"), "action event_id")]
            < index.positions[result_event_id]
            and index.positions[_string(other_event.get("event_id"), "action event_id")]
            > index.positions[action_event_id]
            for other_event in action_events
        ):
            raise ArtifactSourceError(
                f"action {action_event_id} provenance chain interleaves another action"
            )
        request_model_turn_id = _identifier(
            request_event.get("model_turn_id"),
            f"request {request_event_id} model_turn_id",
        )
        for event_id in chain_event_ids[1:]:
            if index.by_id[event_id].get("model_turn_id") != request_model_turn_id:
                raise ArtifactSourceError(
                    f"action {action_event_id} provenance spans multiple model turns"
                )

        actions.append(
            ActionFact(
                request_event_id=request_event_id,
                policy_event_id=policy_event_id,
                action_event_id=action_event_id,
                verification_event_id=verification_event_id,
                result_event_id=result_event_id,
                action=action_name,
                target=target,
                outcome=outcome,
                detail=detail,
                risk=risk,
                policy_decision=policy_decision,
                approval_required=risk == "HIGH",
                approval_id=approval_id,
                verification_status=verification_status,
                verification_detail=verification_detail,
            )
        )

        new_findings = _list(
            action_result.get("new_findings"),
            f"action {action_event_id} new_findings",
        )
        verification_evidence = _list(
            verification.get("evidence"),
            f"verification {verification_event_id} evidence",
        )
        for finding_number, finding in enumerate(new_findings):
            finding_value = _mapping(
                finding,
                f"action {action_event_id} new_findings[{finding_number}]",
            )
            if not any(
                dict(
                    _mapping(
                        candidate,
                        f"verification {verification_event_id} evidence item",
                    )
                )
                == dict(finding_value)
                for candidate in verification_evidence
            ):
                raise ArtifactSourceError(
                    f"action {action_event_id} new finding lacks authoritative evidence"
                )
            new_causes.append(
                _finding(
                    finding_value,
                    event_id=result_event_id,
                    kind="root_cause",
                    incident_id=incident_id,
                )
            )

    if not actions:
        raise ArtifactSourceError("completed trace has no executed recovery actions")
    return tuple(actions), _deduplicate_evidence(new_causes)


def _resolution_summary(
    roots: Sequence[EvidenceFact],
    actions: Sequence[ActionFact],
    *,
    verification_event_id: str,
    verification_status: str,
) -> str:
    root_text = ", ".join(f"{root.code} at {root.event_id}" for root in roots)
    action_text = " -> ".join(
        f"{action.action}({action.target})" for action in actions
    )
    return (
        f"Confirmed root causes: {root_text}. Executed recovery actions: {action_text}. "
        f"Final authoritative verification: {verification_status} at "
        f"{verification_event_id}."
    )


def _prevention_notes(
    roots: Sequence[EvidenceFact],
) -> tuple[str, ...]:
    notes = [
        (
            f"Monitor recurrence of {root.code} from {root.source}; compare new observations "
            f"with evidence {root.event_id}."
        )
        for root in roots
    ]
    notes.append(
        "Keep recovery actions policy-bounded and require authoritative verification before "
        "recording an incident as resolved."
    )
    return tuple(notes)


def extract_incident_facts(
    source: Mapping[str, object],
    *,
    scenario_id: str,
    secret_fields: Sequence[str] = (),
) -> IncidentFacts:
    """Build a fail-closed fact set without inferring resolution from action success."""

    if not isinstance(source, Mapping):
        raise ArtifactSourceError("source trace must be an object")
    scenario = _identifier(scenario_id, "scenario_id")
    index = _build_index(source, secret_fields=secret_fields)

    incident, _ = _incident_data(index)
    incident_id = _identifier(incident.get("incident_id"), "incident.incident_id")
    source_scenario = incident.get("scenario_id")
    if source_scenario is not None and source_scenario != scenario:
        raise ArtifactSourceError("explicit scenario_id conflicts with trace incident data")
    title = _string(incident.get("title"), "incident.title")
    incident_summary = _string(incident.get("summary"), "incident.summary")
    affected_service = _string(
        incident.get("affected_service"), "incident.affected_service"
    )

    action_positions = [
        position
        for position, event in enumerate(index.events, start=1)
        if event.get("event_type") == "action.executed"
    ]
    if not action_positions:
        raise ArtifactSourceError("trace has no executed action")
    first_action_position = action_positions[0]
    initial_environment, environment_event_id = _initial_environment(
        index,
        first_action_position=first_action_position,
    )
    if initial_environment.get("incident_id") != incident_id:
        raise ArtifactSourceError("initial environment belongs to another incident")

    symptoms = _symptoms(
        index,
        incident_id=incident_id,
        first_action_position=first_action_position,
    )
    initial_roots: list[EvidenceFact] = []
    worker_status = _string(
        initial_environment.get("worker_status"), "initial worker_status"
    )
    if worker_status != "running":
        initial_roots.append(
            EvidenceFact(
                event_id=environment_event_id,
                kind="root_cause",
                code=f"worker_status:{worker_status}",
                source="environment",
                summary=f"The initial environment reported worker_status={worker_status}.",
                finding_id=None,
            )
        )

    actions, new_roots = _actions_and_new_causes(index, incident_id=incident_id)
    roots = _deduplicate_evidence((*initial_roots, *new_roots))
    if not roots:
        raise ArtifactSourceError("trace does not contain a confirmed root cause")

    terminal_event = index.events[-1]
    terminal_payload = _event_payload(terminal_event)
    final_status = _string(terminal_payload.get("status"), "terminal status")
    if final_status not in _FINAL_STATUSES:
        raise ArtifactSourceError(f"unsupported terminal status: {final_status}")
    source_result = index.source.get("result")
    if source_result is not None:
        result = _mapping(source_result, "result")
        if result.get("status") != final_status:
            raise ArtifactSourceError("top-level result and terminal event status disagree")

    final_action = actions[-1]
    final_verification_event_id = final_action.verification_event_id
    final_verification_status = final_action.verification_status
    verification_event_ids = [
        _string(event.get("event_id"), "verification event_id")
        for event in index.events
        if event.get("event_type") == "verification.result"
    ]
    if not verification_event_ids or verification_event_ids[-1] != final_verification_event_id:
        raise ArtifactSourceError(
            "the latest authoritative verification is not bound to the final action"
        )
    if final_status == "RESOLVED":
        if final_verification_status != "passed":
            raise ArtifactSourceError(
                "RESOLVED requires the final authoritative verification to be passed"
            )
        if source_result is not None:
            result = _mapping(source_result, "result")
            if (
                result.get("authoritative_pass_observed") is not True
                or result.get("verified_recovery") is not True
            ):
                raise ArtifactSourceError(
                    "RESOLVED top-level result lacks authoritative recovery proof"
                )

    started_at, _ = _timestamp(index.events[0].get("occurred_at"), "run started_at")
    completed_at, _ = _timestamp(terminal_event.get("occurred_at"), "run completed_at")
    resolution_summary = _resolution_summary(
        roots,
        actions,
        verification_event_id=final_verification_event_id,
        verification_status=final_verification_status,
    )

    evidence_ids: set[str] = set()
    for evidence in (*symptoms, *roots):
        evidence_ids.add(evidence.event_id)
    for action in actions:
        evidence_ids.update(
            {
                action.request_event_id,
                action.policy_event_id,
                action.action_event_id,
                action.verification_event_id,
                action.result_event_id,
            }
        )
    if final_verification_event_id is not None:
        evidence_ids.add(final_verification_event_id)
    evidence_event_ids = tuple(
        sorted(evidence_ids, key=lambda event_id: index.positions[event_id])
    )

    return IncidentFacts(
        run_id=index.run_id,
        incident_id=incident_id,
        scenario_id=scenario,
        title=title,
        incident_summary=incident_summary,
        affected_service=affected_service,
        started_at=started_at,
        completed_at=completed_at,
        final_status=final_status,
        symptoms=symptoms,
        confirmed_root_causes=roots,
        rejected_hypotheses=(),
        actions=actions,
        final_verification_event_id=final_verification_event_id,
        final_verification_status=final_verification_status,
        resolution_summary=resolution_summary,
        prevention_follow_up=_prevention_notes(roots),
        evidence_event_ids=evidence_event_ids,
    )
