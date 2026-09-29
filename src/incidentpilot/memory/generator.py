"""Generate structured, exact-match searchable Incident Memory."""

from __future__ import annotations

import re
from datetime import datetime

from incidentpilot.memory.schema import validate_incident_memory
from incidentpilot.reporting.source import ARTIFACT_SCHEMA_VERSION, IncidentFacts

_TOKEN_SPLIT = re.compile(r"[^a-z0-9_.:-]+")


def _generated_at(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("generated_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    return value.isoformat()


def _tokens(facts: IncidentFacts) -> list[str]:
    candidates = [
        facts.scenario_id,
        facts.affected_service,
        facts.final_status,
        facts.title,
        *(item.code for item in facts.symptoms),
        *(item.code for item in facts.confirmed_root_causes),
        *(item.source for item in (*facts.symptoms, *facts.confirmed_root_causes)),
        *(item.action for item in facts.actions),
        *(item.target for item in facts.actions),
    ]
    values: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip().lower()
        if normalized:
            values.add(normalized)
        values.update(token for token in _TOKEN_SPLIT.split(normalized) if token)
    return sorted(values)


def build_incident_memory(
    facts: IncidentFacts,
    *,
    generated_at: datetime,
) -> dict[str, object]:
    if not isinstance(facts, IncidentFacts):
        raise TypeError("facts must be IncidentFacts")
    if facts.final_verification_event_id is None or facts.final_verification_status is None:
        raise ValueError("memory requires an authoritative verification event")
    symptoms = [item.as_dict() for item in facts.symptoms]
    roots = [item.as_dict() for item in facts.confirmed_root_causes]
    rejected = [item.as_dict() for item in facts.rejected_hypotheses]
    memory: dict[str, object] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_type": "incident_memory",
        "memory_id": f"MEMORY-{facts.run_id}",
        "generated_at": _generated_at(generated_at),
        "run_id": facts.run_id,
        "incident_id": facts.incident_id,
        "scenario_id": facts.scenario_id,
        "title": facts.title,
        "affected_service": facts.affected_service,
        "started_at": facts.started_at,
        "completed_at": facts.completed_at,
        "final_status": facts.final_status,
        "symptoms": symptoms,
        "normalized_evidence": [*symptoms, *roots, *rejected],
        "confirmed_root_causes": roots,
        "rejected_hypotheses": rejected,
        "actions": [item.as_dict() for item in facts.actions],
        "resolution": {
            "status": facts.final_status,
            "summary": facts.resolution_summary,
            "verification_event_id": facts.final_verification_event_id,
            "verification_status": facts.final_verification_status,
        },
        "prevention_follow_up": list(facts.prevention_follow_up),
        "lookup_tokens": _tokens(facts),
        "evidence_event_ids": list(facts.evidence_event_ids),
    }
    validate_incident_memory(
        memory,
        available_event_ids=set(facts.evidence_event_ids),
    )
    return memory
