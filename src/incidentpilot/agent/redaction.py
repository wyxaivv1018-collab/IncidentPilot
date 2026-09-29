"""Small deterministic redaction boundary for model-visible run evidence."""

from __future__ import annotations

import re
from typing import Mapping

REDACTED = "[REDACTED]"

_SENSITIVE_KEYS = {
    "api_key",
    "access_key",
    "access_token",
    "auth_token",
    "authorization",
    "client_secret",
    "credential",
    "password",
    "secret_access_key",
    "session_token",
}
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
)


def redact_text(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def redact_json_value(value: object, *, key: str | None = None) -> object:
    normalized_key = key.lower().replace("-", "_") if key is not None else None
    if normalized_key in _SENSITIVE_KEYS:
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_json_value(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, tuple) or isinstance(value, list):
        return [redact_json_value(item) for item in value]
    return value

