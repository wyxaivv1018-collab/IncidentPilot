"""Strict JSON conversion for model-visible tool observations."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Mapping


class InvalidToolResult(TypeError):
    """Raised when a backend returns data outside the bounded JSON contract."""


def to_json_value(value: object) -> object:
    """Convert known typed values to JSON-compatible data, rejecting opaque objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple) or isinstance(value, list):
        return [to_json_value(item) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidToolResult("tool result mapping keys must be strings")
            result[key] = to_json_value(item)
        return result
    raise InvalidToolResult(f"unsupported tool result type: {type(value).__name__}")
