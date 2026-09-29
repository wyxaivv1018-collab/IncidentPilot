"""ASGI application factory for the local C08 demo backend."""

from __future__ import annotations

from pathlib import Path

from incidentpilot.api.asgi import DemoAsgiApp
from incidentpilot.api.runner import DefaultDemoRunner
from incidentpilot.api.service import DemoApiService, DemoRunner
from incidentpilot.reporting.service import ArtifactStore
from incidentpilot.memory.read_tools import KnowledgeReads

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_DIRECTORY = PROJECT_ROOT / "runtime" / "c08" / "artifacts"


def create_app(
    *,
    artifact_directory: str | Path | None = None,
    runner: DemoRunner | None = None,
) -> DemoAsgiApp:
    """Create one process-local API with one active synthetic run at a time."""

    directory = (
        Path(artifact_directory)
        if artifact_directory is not None
        else DEFAULT_ARTIFACT_DIRECTORY
    )
    service = DemoApiService(
        runner=runner or DefaultDemoRunner(knowledge=KnowledgeReads(directory)),
        artifact_store=ArtifactStore(directory),
    )
    return DemoAsgiApp(service)


app = create_app()

__all__ = ["DEFAULT_ARTIFACT_DIRECTORY", "app", "create_app"]
