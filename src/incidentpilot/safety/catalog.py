"""Immutable deny-by-default action catalog for the C04 safety boundary."""

from types import MappingProxyType
from typing import Mapping

from incidentpilot.contracts import ActionName
from incidentpilot.safety.models import ActionScope, ActionSpec, ArgumentRule, RiskLevel
from incidentpilot.simulator import (
    CACHE_TARGET,
    INCIDENT_ID,
    SYNC_JOB_TARGET,
    WORKER_TARGET,
)

RESTART_DATABASE = "restart_database"
MODIFY_PRODUCTION_CONFIG = "modify_production_config"
REPAIR_PRODUCTION_DATA = "repair_production_data"
DELETE_PRODUCTION_DATA = "delete_production_data"

DATABASE_TARGET = "orders-primary"
PRODUCTION_CONFIG_TARGET = "order-sync-service"


def _build_catalog() -> Mapping[str, ActionSpec]:
    specs = (
        ActionSpec(
            action=ActionName.RESTART_NONCRITICAL_WORKER.value,
            risk=RiskLevel.LOW,
            allowed_incident_ids=(INCIDENT_ID,),
            allowed_targets=(WORKER_TARGET,),
            max_scope_size=1,
            exact_scope=ActionScope((WORKER_TARGET,)),
            max_executions_per_run=1,
        ),
        ActionSpec(
            action=ActionName.CLEAR_APPLICATION_CACHE.value,
            risk=RiskLevel.LOW,
            allowed_incident_ids=(INCIDENT_ID,),
            allowed_targets=(CACHE_TARGET,),
            max_scope_size=1,
            exact_scope=ActionScope((CACHE_TARGET,)),
            argument_rules=(
                ArgumentRule("max_keys", tuple(str(value) for value in range(1, 101))),
            ),
            max_executions_per_run=1,
        ),
        ActionSpec(
            action=ActionName.RETRY_SYNC_JOB.value,
            risk=RiskLevel.LOW,
            allowed_incident_ids=(INCIDENT_ID,),
            allowed_targets=(SYNC_JOB_TARGET,),
            max_scope_size=1,
            exact_scope=ActionScope((SYNC_JOB_TARGET,)),
            max_executions_per_run=2,
        ),
        ActionSpec(
            action=RESTART_DATABASE,
            risk=RiskLevel.HIGH,
            allowed_incident_ids=(INCIDENT_ID,),
            allowed_targets=(DATABASE_TARGET,),
            max_scope_size=1,
            exact_scope=ActionScope((DATABASE_TARGET,)),
            argument_rules=(ArgumentRule("strategy", ("rolling",)),),
        ),
        ActionSpec(
            action=MODIFY_PRODUCTION_CONFIG,
            risk=RiskLevel.HIGH,
            allowed_incident_ids=(INCIDENT_ID,),
            allowed_targets=(PRODUCTION_CONFIG_TARGET,),
            max_scope_size=1,
            exact_scope=ActionScope((PRODUCTION_CONFIG_TARGET,)),
            argument_rules=(ArgumentRule("change_mode", ("validated_patch",)),),
            requires_rollback=True,
        ),
        ActionSpec(
            action=REPAIR_PRODUCTION_DATA,
            risk=RiskLevel.HIGH,
            allowed_incident_ids=(INCIDENT_ID,),
            allowed_targets=(DATABASE_TARGET,),
            max_scope_size=100,
            scope_pattern=r"record:[1-9][0-9]*",
            argument_rules=(ArgumentRule("operation", ("repair_consistency",)),),
            requires_backup=True,
            requires_rollback=True,
        ),
        ActionSpec(
            action=DELETE_PRODUCTION_DATA,
            risk=RiskLevel.CRITICAL,
            allowed_incident_ids=(INCIDENT_ID,),
            allowed_targets=(DATABASE_TARGET,),
            max_scope_size=1,
            scope_pattern=r"record:[1-9][0-9]*",
        ),
    )
    return MappingProxyType({spec.action: spec for spec in specs})


ACTION_CATALOG = _build_catalog()
