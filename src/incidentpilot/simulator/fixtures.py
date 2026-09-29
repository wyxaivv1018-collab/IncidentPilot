"""Immutable fixture data for the local order-sync scenario."""

from incidentpilot.contracts import Incident, LogCode, LogFinding

SCENARIO_ID = "order-sync-double-fault"
INCIDENT_ID = "INC-ORDER-SYNC-001"
WORKER_TARGET = "sync-worker"
CACHE_TARGET = "order-sync"
SYNC_JOB_TARGET = "order-sync-job-001"

ORDER_SYNC_INCIDENT = Incident(
    incident_id=INCIDENT_ID,
    scenario_id=SCENARIO_ID,
    title="Order synchronization failed",
    summary="The synthetic order synchronization job is currently failing.",
    affected_service="order-sync",
)

SYNC_TIMEOUT_FINDING = LogFinding(
    finding_id="LOG-ORDER-SYNC-001",
    incident_id=INCIDENT_ID,
    code=LogCode.SYNC_TIMEOUT,
    source="order-sync",
    message="The order synchronization request timed out.",
)

CACHE_LOCK_FINDING = LogFinding(
    finding_id="LOG-ORDER-SYNC-002",
    incident_id=INCIDENT_ID,
    code=LogCode.CACHE_LOCK,
    source="order-sync-cache",
    message="The order-sync application cache namespace is locked.",
)
