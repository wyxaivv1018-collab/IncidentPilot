"""Atomic per-run action-use limits for LOW risk operations."""

from __future__ import annotations

from threading import RLock

from incidentpilot.safety.models import SafetyActionRequest


class ActionUsageRegistry:
    """Reserve execution attempts by run, incident, action, and exact target."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str, str, str], int] = {}
        self._lock = RLock()

    def can_execute(self, request: SafetyActionRequest, *, maximum: int) -> bool:
        self._validate(request, maximum)
        with self._lock:
            return self._counts.get(self._key(request), 0) < maximum

    def reserve(self, request: SafetyActionRequest, *, maximum: int) -> bool:
        """Atomically consume one attempt before the handler can be invoked."""
        self._validate(request, maximum)
        with self._lock:
            key = self._key(request)
            current = self._counts.get(key, 0)
            if current >= maximum:
                return False
            self._counts[key] = current + 1
            return True

    def count(self, request: SafetyActionRequest) -> int:
        if not isinstance(request, SafetyActionRequest):
            raise TypeError("request must be a SafetyActionRequest")
        with self._lock:
            return self._counts.get(self._key(request), 0)

    @staticmethod
    def _key(request: SafetyActionRequest) -> tuple[str, str, str, str]:
        return request.run_id, request.incident_id, request.action, request.target

    @staticmethod
    def _validate(request: SafetyActionRequest, maximum: int) -> None:
        if not isinstance(request, SafetyActionRequest):
            raise TypeError("request must be a SafetyActionRequest")
        if not isinstance(maximum, int) or maximum < 1:
            raise ValueError("maximum must be a positive integer")
