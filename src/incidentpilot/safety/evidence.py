"""Authoritative backup and rollback evidence used by the safety policy."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from incidentpilot.safety.models import (
    ActionScope,
    BackupEvidence,
    BackupStatus,
    RollbackEvidence,
    RollbackStatus,
)


def _backup_payload(evidence: BackupEvidence) -> bytes:
    data = {
        "backup_id": evidence.backup_id,
        "run_id": evidence.run_id,
        "incident_id": evidence.incident_id,
        "target": evidence.target,
        "covered_scope": evidence.covered_scope.resources,
        "status": evidence.status.value,
        "created_at": evidence.created_at.isoformat(),
        "verified_at": evidence.verified_at.isoformat() if evidence.verified_at else None,
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _rollback_payload(evidence: RollbackEvidence) -> bytes:
    data = {
        "rollback_id": evidence.rollback_id,
        "run_id": evidence.run_id,
        "incident_id": evidence.incident_id,
        "action": evidence.action,
        "target": evidence.target,
        "covered_scope": evidence.covered_scope.resources,
        "status": evidence.status.value,
        "declared_at": evidence.declared_at.isoformat(),
        "verified_at": evidence.verified_at.isoformat() if evidence.verified_at else None,
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SafetyEvidenceRegistry:
    """Store trusted evidence; action requests carry identifiers, never truth booleans."""

    def __init__(self) -> None:
        self._backups: dict[str, BackupEvidence] = {}
        self._backup_tags: dict[str, bytes] = {}
        self._rollbacks: dict[str, RollbackEvidence] = {}
        self._rollback_tags: dict[str, bytes] = {}
        self._seal_key = secrets.token_bytes(32)
        self._lock = RLock()

    def record_backup(
        self,
        *,
        run_id: str,
        incident_id: str,
        target: str,
        covered_scope: ActionScope,
        created_at: datetime | None = None,
        backup_id: str | None = None,
    ) -> BackupEvidence:
        evidence = BackupEvidence(
            backup_id=backup_id or f"BKP-{uuid4().hex}",
            run_id=run_id,
            incident_id=incident_id,
            target=target,
            covered_scope=covered_scope,
            status=BackupStatus.CREATED,
            created_at=created_at or datetime.now(timezone.utc),
        )
        with self._lock:
            if evidence.backup_id in self._backups:
                raise ValueError(f"backup evidence already exists: {evidence.backup_id}")
            self._store_backup(evidence)
        return evidence

    def verify_backup_recoverable(
        self,
        backup_id: str,
        *,
        verified_at: datetime | None = None,
    ) -> BackupEvidence:
        with self._lock:
            current = self._backups.get(backup_id)
            if current is None:
                raise KeyError(backup_id)
            if not self._backup_integrity_valid(current):
                raise ValueError("backup evidence integrity check failed")
            verified = replace(
                current,
                status=BackupStatus.VERIFIED_RECOVERABLE,
                verified_at=verified_at or datetime.now(timezone.utc),
            )
            self._store_backup(verified)
            return verified

    def inspect_backup(self, backup_id: str) -> tuple[BackupEvidence | None, bool]:
        with self._lock:
            evidence = self._backups.get(backup_id)
            if evidence is None:
                return None, True
            return evidence, self._backup_integrity_valid(evidence)

    def record_rollback(
        self,
        *,
        run_id: str,
        incident_id: str,
        action: str,
        target: str,
        covered_scope: ActionScope,
        declared_at: datetime | None = None,
        rollback_id: str | None = None,
    ) -> RollbackEvidence:
        evidence = RollbackEvidence(
            rollback_id=rollback_id or f"RBK-{uuid4().hex}",
            run_id=run_id,
            incident_id=incident_id,
            action=action,
            target=target,
            covered_scope=covered_scope,
            status=RollbackStatus.DECLARED,
            declared_at=declared_at or datetime.now(timezone.utc),
        )
        with self._lock:
            if evidence.rollback_id in self._rollbacks:
                raise ValueError(f"rollback evidence already exists: {evidence.rollback_id}")
            self._store_rollback(evidence)
        return evidence

    def verify_rollback_ready(
        self,
        rollback_id: str,
        *,
        verified_at: datetime | None = None,
    ) -> RollbackEvidence:
        with self._lock:
            current = self._rollbacks.get(rollback_id)
            if current is None:
                raise KeyError(rollback_id)
            if not self._rollback_integrity_valid(current):
                raise ValueError("rollback evidence integrity check failed")
            verified = replace(
                current,
                status=RollbackStatus.VERIFIED_READY,
                verified_at=verified_at or datetime.now(timezone.utc),
            )
            self._store_rollback(verified)
            return verified

    def inspect_rollback(self, rollback_id: str) -> tuple[RollbackEvidence | None, bool]:
        with self._lock:
            evidence = self._rollbacks.get(rollback_id)
            if evidence is None:
                return None, True
            return evidence, self._rollback_integrity_valid(evidence)

    def _store_backup(self, evidence: BackupEvidence) -> None:
        self._backups[evidence.backup_id] = evidence
        self._backup_tags[evidence.backup_id] = hmac.new(
            self._seal_key,
            _backup_payload(evidence),
            hashlib.sha256,
        ).digest()

    def _backup_integrity_valid(self, evidence: BackupEvidence) -> bool:
        expected = self._backup_tags.get(evidence.backup_id)
        if expected is None:
            return False
        actual = hmac.new(
            self._seal_key,
            _backup_payload(evidence),
            hashlib.sha256,
        ).digest()
        return hmac.compare_digest(expected, actual)

    def _store_rollback(self, evidence: RollbackEvidence) -> None:
        self._rollbacks[evidence.rollback_id] = evidence
        self._rollback_tags[evidence.rollback_id] = hmac.new(
            self._seal_key,
            _rollback_payload(evidence),
            hashlib.sha256,
        ).digest()

    def _rollback_integrity_valid(self, evidence: RollbackEvidence) -> bool:
        expected = self._rollback_tags.get(evidence.rollback_id)
        if expected is None:
            return False
        actual = hmac.new(
            self._seal_key,
            _rollback_payload(evidence),
            hashlib.sha256,
        ).digest()
        return hmac.compare_digest(expected, actual)
