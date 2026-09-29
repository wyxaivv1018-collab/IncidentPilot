"""Bounded deterministic lookup for locally persisted synthetic memories."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from incidentpilot.memory.schema import validate_incident_memory

_TOKEN_SPLIT = re.compile(r"[^a-z0-9_.:-]+")


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    text: str = ""
    scenario_id: str | None = None
    affected_service: str | None = None
    final_status: str | None = None
    limit: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        for field_name in ("scenario_id", "affected_service", "final_status"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be a non-empty string when supplied")
        if not isinstance(self.limit, int) or not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")


def _query_tokens(value: str) -> tuple[str, ...]:
    normalized = value.strip().lower()
    if not normalized:
        return ()
    return tuple(token for token in _TOKEN_SPLIT.split(normalized) if token)


def lookup_incident_memories(
    memories: Sequence[Mapping[str, object]],
    query: MemoryQuery,
) -> tuple[Mapping[str, object], ...]:
    """Return exact-filtered/token-matched records with deterministic ordering."""

    if not isinstance(query, MemoryQuery):
        raise TypeError("query must be MemoryQuery")
    tokens = _query_tokens(query.text)
    matches: list[Mapping[str, object]] = []
    for memory in memories:
        validate_incident_memory(memory)
        if query.scenario_id is not None and memory["scenario_id"] != query.scenario_id:
            continue
        if (
            query.affected_service is not None
            and memory["affected_service"] != query.affected_service
        ):
            continue
        if query.final_status is not None and memory["final_status"] != query.final_status:
            continue
        lookup_tokens = memory["lookup_tokens"]
        assert isinstance(lookup_tokens, list)
        searchable = set(str(item) for item in lookup_tokens)
        if any(token not in searchable for token in tokens):
            continue
        matches.append(memory)

    def ordering(memory: Mapping[str, object]) -> tuple[float, str]:
        completed = str(memory["completed_at"])
        timestamp = datetime.fromisoformat(completed.replace("Z", "+00:00")).timestamp()
        return (-timestamp, str(memory["memory_id"]))

    matches.sort(key=ordering)
    return tuple(matches[: query.limit])

