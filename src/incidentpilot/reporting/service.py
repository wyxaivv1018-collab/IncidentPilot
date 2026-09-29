"""Generate and persist the C07 report/memory artifact pair."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from incidentpilot.memory.generator import build_incident_memory
from incidentpilot.memory.lookup import MemoryQuery, lookup_incident_memories
from incidentpilot.memory.schema import validate_incident_memory
from incidentpilot.reporting.generator import build_incident_report, render_incident_report
from incidentpilot.reporting.schema import validate_incident_report
from incidentpilot.reporting.source import (
    ArtifactValidationError,
    extract_incident_facts,
)

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REPORT_JSON_NAME = "incident-report.json"
_REPORT_MARKDOWN_NAME = "incident-report.md"
_MEMORY_JSON_NAME = "incident-memory.json"


@dataclass(frozen=True, slots=True)
class ArtifactBundle:
    report: Mapping[str, object]
    report_markdown: str
    memory: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    directory: Path
    report_json: Path
    report_markdown: Path
    memory_json: Path


def _canonical_action(value: object) -> tuple[object, ...]:
    if not isinstance(value, Mapping):
        raise ArtifactValidationError("artifact action must be an object")
    fields = (
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
    return tuple(value.get(field) for field in fields)


def _canonical_evidence(value: object) -> tuple[object, ...]:
    if not isinstance(value, Mapping):
        raise ArtifactValidationError("artifact evidence must be an object")
    fields = ("event_id", "kind", "code", "source", "summary", "finding_id")
    return tuple(value.get(field) for field in fields)


def validate_artifact_consistency(
    report: Mapping[str, object],
    memory: Mapping[str, object],
) -> None:
    """Require both artifacts to tell the same evidence-backed incident story."""

    validate_incident_report(report)
    validate_incident_memory(memory)
    for field in (
        "schema_version",
        "generated_at",
        "run_id",
        "incident_id",
        "scenario_id",
        "title",
        "affected_service",
        "started_at",
        "completed_at",
        "final_status",
    ):
        if report[field] != memory[field]:
            raise ArtifactValidationError(f"report and memory disagree on {field}")

    report_symptoms = report["symptoms"]
    memory_symptoms = memory["symptoms"]
    report_roots = report["confirmed_root_causes"]
    memory_roots = memory["confirmed_root_causes"]
    report_actions = report["actions"]
    memory_actions = memory["actions"]
    assert isinstance(report_symptoms, list)
    assert isinstance(memory_symptoms, list)
    assert isinstance(report_roots, list)
    assert isinstance(memory_roots, list)
    assert isinstance(report_actions, list)
    assert isinstance(memory_actions, list)
    if [_canonical_evidence(item) for item in report_symptoms] != [
        _canonical_evidence(item) for item in memory_symptoms
    ]:
        raise ArtifactValidationError("report and memory symptoms disagree")
    if [_canonical_evidence(item) for item in report_roots] != [
        _canonical_evidence(item) for item in memory_roots
    ]:
        raise ArtifactValidationError("report and memory root causes disagree")
    if [_canonical_action(item) for item in report_actions] != [
        _canonical_action(item) for item in memory_actions
    ]:
        raise ArtifactValidationError("report and memory actions disagree")

    outcome = report["outcome"]
    resolution = memory["resolution"]
    if not isinstance(outcome, Mapping) or not isinstance(resolution, Mapping):
        raise ArtifactValidationError("artifact outcome/resolution must be objects")
    if dict(outcome) != dict(resolution):
        raise ArtifactValidationError("report outcome and memory resolution disagree")
    for field in ("prevention_follow_up", "evidence_event_ids"):
        if report[field] != memory[field]:
            raise ArtifactValidationError(f"report and memory disagree on {field}")


def build_artifacts(
    source: Mapping[str, object],
    *,
    scenario_id: str,
    secret_fields: Sequence[str] = (),
    clock: Callable[[], datetime] | None = None,
) -> ArtifactBundle:
    """Generate one mutually consistent artifact pair from a completed trace."""

    generated_at = (clock or (lambda: datetime.now(timezone.utc)))()
    if not isinstance(generated_at, datetime):
        raise TypeError("artifact clock must return datetime")
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("artifact clock must return a timezone-aware datetime")
    facts = extract_incident_facts(
        source,
        scenario_id=scenario_id,
        secret_fields=secret_fields,
    )
    report = build_incident_report(facts, generated_at=generated_at)
    memory = build_incident_memory(facts, generated_at=generated_at)
    validate_artifact_consistency(report, memory)
    markdown = render_incident_report(report)
    return ArtifactBundle(report=report, report_markdown=markdown, memory=memory)


class ArtifactStore:
    """Local JSON/Markdown store with atomic bundle publication and strict read-back."""

    def __init__(self, base_directory: str | Path) -> None:
        self.base_directory = Path(base_directory)

    @staticmethod
    def _run_id(value: object) -> str:
        if not isinstance(value, str) or _SAFE_RUN_ID.fullmatch(value) is None:
            raise ArtifactValidationError("run_id is not a safe storage identifier")
        return value

    def _paths(self, run_id: str) -> ArtifactPaths:
        safe_run_id = self._run_id(run_id)
        directory = self.base_directory / safe_run_id
        return ArtifactPaths(
            directory=directory,
            report_json=directory / _REPORT_JSON_NAME,
            report_markdown=directory / _REPORT_MARKDOWN_NAME,
            memory_json=directory / _MEMORY_JSON_NAME,
        )

    @staticmethod
    def _json_text(value: Mapping[str, object]) -> str:
        return json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        ) + "\n"

    def save(self, bundle: ArtifactBundle) -> ArtifactPaths:
        if not isinstance(bundle, ArtifactBundle):
            raise TypeError("bundle must be ArtifactBundle")
        validate_artifact_consistency(bundle.report, bundle.memory)
        expected_markdown = render_incident_report(bundle.report)
        if bundle.report_markdown != expected_markdown:
            raise ArtifactValidationError("report Markdown does not match report JSON")
        run_id = self._run_id(bundle.report["run_id"])
        target = self._paths(run_id)
        self.base_directory.mkdir(parents=True, exist_ok=True)
        if target.directory.exists():
            raise FileExistsError(f"artifact bundle already exists for run {run_id}")

        with TemporaryDirectory(prefix=".artifact-staging-", dir=self.base_directory) as temporary:
            staging = Path(temporary)
            (staging / _REPORT_JSON_NAME).write_text(
                self._json_text(bundle.report),
                encoding="utf-8",
            )
            (staging / _REPORT_MARKDOWN_NAME).write_text(
                bundle.report_markdown,
                encoding="utf-8",
            )
            (staging / _MEMORY_JSON_NAME).write_text(
                self._json_text(bundle.memory),
                encoding="utf-8",
            )
            staging.rename(target.directory)
        return target

    @staticmethod
    def _read_json(path: Path) -> Mapping[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactValidationError(f"cannot read valid JSON from {path.name}") from exc
        if not isinstance(value, Mapping):
            raise ArtifactValidationError(f"{path.name} must contain a JSON object")
        return value

    def load(self, run_id: str) -> ArtifactBundle:
        paths = self._paths(run_id)
        report = self._read_json(paths.report_json)
        memory = self._read_json(paths.memory_json)
        try:
            markdown = paths.report_markdown.read_text(encoding="utf-8")
        except OSError as exc:
            raise ArtifactValidationError("cannot read Incident Report Markdown") from exc
        validate_artifact_consistency(report, memory)
        if markdown != render_incident_report(report):
            raise ArtifactValidationError("persisted Report Markdown disagrees with JSON")
        return ArtifactBundle(report=report, report_markdown=markdown, memory=memory)

    def memories(self) -> tuple[Mapping[str, object], ...]:
        if not self.base_directory.exists():
            return ()
        base = self.base_directory.resolve()
        values: list[Mapping[str, object]] = []
        for path in sorted(self.base_directory.glob(f"*/{_MEMORY_JSON_NAME}")):
            if path.is_symlink():
                raise ArtifactValidationError("memory store refuses symbolic-link records")
            resolved = path.resolve()
            if not resolved.is_relative_to(base):
                raise ArtifactValidationError("memory record escapes the configured store")
            value = self._read_json(path)
            validate_incident_memory(value)
            values.append(value)
        return tuple(values)

    def search(self, query: MemoryQuery) -> tuple[Mapping[str, object], ...]:
        return lookup_incident_memories(self.memories(), query)
