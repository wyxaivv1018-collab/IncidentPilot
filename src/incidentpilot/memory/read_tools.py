"""Bounded read-only knowledge adapters; no models, actions or memory generation."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from incidentpilot.memory.demo_sop import SOPS
from incidentpilot.memory.lookup import MemoryQuery, lookup_incident_memories

MAX_QUERY = 256
MAX_RESULTS = 5
MAX_RECORD_BYTES = 262144
MAX_STORE_ENTRIES = 100
MAX_RESULT_BYTES = 16384
DEFAULT_MEMORY_DIRECTORY = Path(__file__).resolve().parents[3] / "runtime/c08/artifacts"


_STOP_WORDS = frozenset(
    "a an and are as at be by can could do for from how i in is it of on or please "
    "show me the this to was were what when where which with would lookup find search".split()
)


def _meaningful_tokens(text: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return frozenset(
        token for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) > 1 and not token.isdecimal() and token not in _STOP_WORDS
    )


@dataclass(frozen=True, slots=True)
class KnowledgeResult:
    outcome: str
    evidence_kind: str
    establishes_resolution: bool
    matches: tuple[dict[str, object], ...]


def _tokens(query: str, limit: int) -> tuple[str, ...]:
    if not isinstance(query, str) or not 1 <= len(query) <= MAX_QUERY:
        raise ValueError("query must contain 1..256 characters")
    if any(ord(char) < 32 for char in query):
        raise ValueError("query must not contain control characters")
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
        raise ValueError("limit must be an integer from 1..5")
    tokens = tuple(filter(None, re.split(r"[^a-z0-9_.:-]+", query.lower())))
    if not tokens:
        raise ValueError("query must contain searchable tokens")
    return tokens


def _result(kind: str, matches: list[dict[str, object]]) -> KnowledgeResult:
    result = KnowledgeResult("match" if matches else "no-match", kind, False, tuple(matches))
    if len(json.dumps(asdict(result), ensure_ascii=True).encode()) > MAX_RESULT_BYTES:
        raise ValueError("knowledge result exceeds size limit")
    return result


class KnowledgeReads:
    """Trusted directory configuration only; model input cannot select file paths."""

    def __init__(self, memory_directory: str | Path = DEFAULT_MEMORY_DIRECTORY) -> None:
        self._memory_directory = Path(memory_directory)

    def memory(self, query: str, limit: int = 5, *, exclude_run_id: str) -> KnowledgeResult:
        _tokens(query, limit)
        base = self._memory_directory
        records = []
        if base.exists():
            if base.is_symlink() or not base.is_dir():
                raise ValueError("invalid memory directory")
            resolved_base = base.resolve()
            for index, directory in enumerate(base.iterdir()):
                if index >= MAX_STORE_ENTRIES:
                    raise ValueError("memory store exceeds scan bound")
                if directory.is_symlink() or not directory.resolve().is_relative_to(resolved_base):
                    raise ValueError("memory directory escapes store")
                path = directory / "incident-memory.json"
                if not directory.is_dir() or not path.exists():
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(resolved_base):
                    raise ValueError("memory record escapes store")
                with path.open("rb") as stream:
                    raw = stream.read(MAX_RECORD_BYTES + 1)
                if len(raw) > MAX_RECORD_BYTES:
                    raise ValueError("memory record exceeds size bound")
                record = json.loads(raw)
                # Existing lookup validates every record before matching.
                lookup_incident_memories([record], MemoryQuery(text=query, limit=limit))
                if record["run_id"] != exclude_run_id:
                    records.append(record)
        matches = lookup_incident_memories(records, MemoryQuery(text=query, limit=limit))
        fields = ("memory_id", "run_id", "incident_id", "affected_service", "symptoms",
                  "confirmed_root_causes", "resolution", "evidence_event_ids")
        return _result("historical-memory-not-current-fact", [
            {key: record[key] for key in fields} for record in matches
        ])

    def sop(self, query: str, limit: int = 5) -> KnowledgeResult:
        _tokens(query, limit)
        tokens = _meaningful_tokens(query)
        ranked = []
        for sop in SOPS:
            # Search curated subjects, not generic safety prose.
            subject = _meaningful_tokens(" ".join((*sop.tokens, sop.title)))
            overlap = len(tokens & subject)
            if overlap:
                ranked.append((-overlap, sop.sop_id, sop))
        ranked.sort(key=lambda item: (item[0], item[1]))
        return _result("synthetic-demo-sop-not-current-fact", [
            asdict(sop) for _, _, sop in ranked[:limit]
        ])
