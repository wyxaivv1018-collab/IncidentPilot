"""Dependency-free ASGI transport for the narrow C08 local API contract."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs

from incidentpilot.api.contracts import (
    API_SCHEMA_VERSION,
    DEMO_SCENARIO_ID,
    ApiError,
    ApiErrorCode,
)
from incidentpilot.api.service import DemoApiService
from incidentpilot.safety import ActionArgument, ActionScope

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

_MAX_REQUEST_BYTES = 64 * 1024
_JSON_HEADERS = ((b"content-type", b"application/json; charset=utf-8"),)


class _StrictJsonError(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _StrictJsonError("duplicate JSON object key")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise _StrictJsonError(f"non-standard JSON constant: {value}")


class DemoAsgiApp:
    """Expose only run orchestration, approval confirmation, and read endpoints."""

    def __init__(self, service: DemoApiService) -> None:
        if not isinstance(service, DemoApiService):
            raise TypeError("service must be a DemoApiService")
        self.service = service

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope_type != "http":
            return
        try:
            if await self._route(scope, receive, send):
                return
        except ApiError as error:
            await self._send_json(send, error.status_code, error.as_dict())
            return
        except Exception:
            error = ApiError(
                status_code=500,
                code=ApiErrorCode.INTERNAL_ERROR,
                message="The local API request failed safely.",
            )
            await self._send_json(send, error.status_code, error.as_dict())

    async def _route(
        self,
        scope: dict[str, Any],
        receive: Receive,
        send: Send,
    ) -> bool:
        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", ""))
        self._require_local_request(scope, method)
        segments = [segment for segment in path.split("/") if segment]
        if segments == ["api", "v1", "runs"]:
            self._require_method(method, "POST")
            body = await self._json_body(receive)
            self._require_keys(body, allowed={"scenario_id"})
            scenario_id = body.get("scenario_id", DEMO_SCENARIO_ID)
            if not isinstance(scenario_id, str):
                raise self._invalid_request("scenario_id must be a string.")
            value = self.service.start_run(scenario_id=scenario_id)
            await self._send_json(send, 202, value)
            return True

        if len(segments) < 4 or segments[:3] != ["api", "v1", "runs"]:
            raise self._route_not_found()
        run_id = segments[3]
        if len(segments) == 4:
            self._require_method(method, "GET")
            await self._send_json(send, 200, self.service.get_status(run_id))
            return True
        if len(segments) == 5 and segments[4] == "cancel":
            self._require_method(method, "POST")
            self._require_empty_body(await self._json_body(receive))
            await self._send_json(send, 202, self.service.cancel_run(run_id))
            return True
        if len(segments) == 5 and segments[4] == "events":
            self._require_method(method, "GET")
            after = self._event_cursor(scope)
            await self._send_json(
                send,
                200,
                self.service.get_events(run_id, after=after),
            )
            return True
        if len(segments) == 6 and segments[4:6] == ["events", "stream"]:
            self._require_method(method, "GET")
            await self._stream_events(
                send,
                run_id,
                after=self._event_cursor(scope),
            )
            return True
        if len(segments) == 5 and segments[4] == "report":
            self._require_method(method, "GET")
            await self._send_json(send, 200, self.service.get_report(run_id))
            return True
        if len(segments) == 5 and segments[4] == "memory":
            self._require_method(method, "GET")
            await self._send_json(send, 200, self.service.get_memory(run_id))
            return True
        if len(segments) == 6 and segments[4] == "approvals":
            self._require_method(method, "POST")
            approval = self._approval_body(await self._json_body(receive))
            value = self.service.approve(
                run_id,
                segments[5],
                action=approval["action"],
                target=approval["target"],
                scope=approval["scope"],
                arguments=approval["arguments"],
            )
            await self._send_json(send, 200, value)
            return True
        raise self._route_not_found()

    @classmethod
    def _require_local_request(cls, scope: dict[str, Any], method: str) -> None:
        host_values = cls._header_values(scope, b"host")
        server = scope.get("server")
        if (
            len(host_values) != 1
            or not isinstance(server, (tuple, list))
            or len(server) != 2
            or server[0] != "127.0.0.1"
            or not isinstance(server[1], int)
        ):
            raise cls._untrusted_request()
        authority = host_values[0].strip().lower()
        trusted_authorities = {"127.0.0.1", f"127.0.0.1:{server[1]}"}
        if authority not in trusted_authorities:
            raise cls._untrusted_request()

        origin_values = cls._header_values(scope, b"origin")
        if len(origin_values) > 1:
            raise cls._untrusted_request()
        if origin_values and origin_values[0].strip().lower() != f"http://{authority}":
            raise cls._untrusted_request()

        if method == "POST":
            content_types = cls._header_values(scope, b"content-type")
            if (
                len(content_types) != 1
                or content_types[0].split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                raise ApiError(
                    status_code=415,
                    code=ApiErrorCode.UNSUPPORTED_MEDIA_TYPE,
                    message="Local API mutations require Content-Type application/json.",
                )

    @staticmethod
    def _header_values(scope: dict[str, Any], name: bytes) -> list[str]:
        headers = scope.get("headers", ())
        if not isinstance(headers, (tuple, list)):
            return []
        values: list[str] = []
        for item in headers:
            if (
                not isinstance(item, (tuple, list))
                or len(item) != 2
                or not isinstance(item[0], bytes)
                or not isinstance(item[1], bytes)
            ):
                return []
            if item[0].lower() == name:
                try:
                    values.append(item[1].decode("latin-1"))
                except UnicodeDecodeError:
                    return []
        return values

    @staticmethod
    def _untrusted_request() -> ApiError:
        return ApiError(
            status_code=403,
            code=ApiErrorCode.UNTRUSTED_REQUEST,
            message="The local API accepts only same-origin loopback requests.",
        )

    async def _stream_events(self, send: Send, run_id: str, *, after: int) -> None:
        initial = self.service.get_events(run_id, after=after)
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/event-stream; charset=utf-8"),
                    (b"cache-control", b"no-store"),
                    (b"x-accel-buffering", b"no"),
                ],
            }
        )
        snapshot = initial
        cursor = after
        while True:
            for event in snapshot["events"]:
                cursor = int(event["sequence"])
                payload = self._json_bytes(event).decode("utf-8")
                chunk = (
                    f"id: {cursor}\n"
                    f"event: {event['event_type']}\n"
                    f"data: {payload}\n\n"
                ).encode("utf-8")
                await send(
                    {
                        "type": "http.response.body",
                        "body": chunk,
                        "more_body": True,
                    }
                )
            if snapshot["terminal"]:
                end = self._json_bytes(
                    {
                        "schema_version": API_SCHEMA_VERSION,
                        "run_id": run_id,
                        "status": snapshot["status"],
                        "next_after": cursor,
                    }
                ).decode("utf-8")
                await send(
                    {
                        "type": "http.response.body",
                        "body": f"event: stream.end\ndata: {end}\n\n".encode("utf-8"),
                        "more_body": False,
                    }
                )
                return
            snapshot = await asyncio.to_thread(
                self.service.wait_for_events,
                run_id,
                after=cursor,
                timeout_seconds=0.25,
            )

    @staticmethod
    async def _lifespan(receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message.get("type") == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message.get("type") == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    @staticmethod
    async def _json_body(receive: Receive) -> Mapping[str, object]:
        body = bytearray()
        more = True
        while more:
            message = await receive()
            if message.get("type") == "http.disconnect":
                raise ApiError(
                    status_code=400,
                    code=ApiErrorCode.INVALID_REQUEST,
                    message="The client disconnected before the request was complete.",
                )
            if message.get("type") != "http.request":
                continue
            chunk = message.get("body", b"")
            if not isinstance(chunk, bytes):
                raise ApiError(
                    status_code=400,
                    code=ApiErrorCode.INVALID_REQUEST,
                    message="The request body was invalid.",
                )
            body.extend(chunk)
            if len(body) > _MAX_REQUEST_BYTES:
                raise ApiError(
                    status_code=413,
                    code=ApiErrorCode.REQUEST_TOO_LARGE,
                    message="The JSON request body exceeds 64 KiB.",
                )
            more = bool(message.get("more_body", False))
        if not body:
            return {}
        try:
            value = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, _StrictJsonError):
            raise ApiError(
                status_code=400,
                code=ApiErrorCode.INVALID_JSON,
                message="The request body must be one valid UTF-8 JSON object.",
            ) from None
        if not isinstance(value, Mapping) or not all(
            isinstance(key, str) for key in value
        ):
            raise ApiError(
                status_code=422,
                code=ApiErrorCode.INVALID_REQUEST,
                message="The JSON request body must be an object with string keys.",
            )
        return value

    @classmethod
    def _approval_body(cls, body: Mapping[str, object]) -> dict[str, object]:
        cls._require_keys(
            body,
            allowed={"action", "target", "scope", "arguments"},
            required={"action", "target", "scope", "arguments"},
        )
        action = body["action"]
        target = body["target"]
        scope_value = body["scope"]
        arguments_value = body["arguments"]
        if not isinstance(action, str) or not action.strip():
            raise cls._invalid_request("action must be a non-empty string.")
        if not isinstance(target, str) or not target.strip():
            raise cls._invalid_request("target must be a non-empty string.")
        if not isinstance(scope_value, list) or not scope_value or not all(
            isinstance(item, str) and item.strip() for item in scope_value
        ):
            raise cls._invalid_request("scope must be a non-empty array of strings.")
        if not isinstance(arguments_value, Mapping) or not all(
            isinstance(key, str)
            and key.strip()
            and isinstance(value, str)
            and value.strip()
            for key, value in arguments_value.items()
        ):
            raise cls._invalid_request("arguments must be an object of string values.")
        try:
            scope = ActionScope(tuple(scope_value))
            arguments = tuple(
                ActionArgument(name, value)
                for name, value in sorted(arguments_value.items())
            )
        except (TypeError, ValueError):
            raise cls._invalid_request("The approval binding is invalid.") from None
        return {
            "action": action,
            "target": target,
            "scope": scope,
            "arguments": arguments,
        }

    @classmethod
    def _event_cursor(cls, scope: Mapping[str, object]) -> int:
        raw = scope.get("query_string", b"")
        if not isinstance(raw, bytes):
            raise cls._invalid_request("The query string was invalid.")
        try:
            values = parse_qs(
                raw.decode("ascii"),
                keep_blank_values=True,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError):
            raise cls._invalid_request("The event query string was invalid.") from None
        if set(values) - {"after"} or len(values.get("after", [])) > 1:
            raise cls._invalid_request("Only one after cursor is supported.")
        text = values.get("after", ["0"])[0]
        try:
            after = int(text)
        except ValueError:
            raise ApiError(
                status_code=422,
                code=ApiErrorCode.INVALID_EVENT_CURSOR,
                message="The event cursor must be a non-negative integer.",
            ) from None
        if after < 0:
            raise ApiError(
                status_code=422,
                code=ApiErrorCode.INVALID_EVENT_CURSOR,
                message="The event cursor must be a non-negative integer.",
            )
        return after

    @classmethod
    def _require_empty_body(cls, body: Mapping[str, object]) -> None:
        cls._require_keys(body, allowed=set())

    @classmethod
    def _require_keys(
        cls,
        body: Mapping[str, object],
        *,
        allowed: set[str],
        required: set[str] | None = None,
    ) -> None:
        keys = set(body)
        missing = set(required or ()) - keys
        extra = keys - allowed
        if missing or extra:
            raise cls._invalid_request("The JSON object has missing or unsupported fields.")

    @staticmethod
    def _require_method(method: str, allowed: str) -> None:
        if method != allowed:
            raise ApiError(
                status_code=405,
                code=ApiErrorCode.METHOD_NOT_ALLOWED,
                message=f"This endpoint requires {allowed}.",
                details={"allowed": [allowed]},
            )

    @staticmethod
    def _route_not_found() -> ApiError:
        return ApiError(
            status_code=404,
            code=ApiErrorCode.ROUTE_NOT_FOUND,
            message="The requested local API route does not exist.",
        )

    @staticmethod
    def _invalid_request(message: str) -> ApiError:
        return ApiError(
            status_code=422,
            code=ApiErrorCode.INVALID_REQUEST,
            message=message,
        )

    @classmethod
    async def _send_json(
        cls,
        send: Send,
        status: int,
        value: Mapping[str, object],
    ) -> None:
        body = cls._json_bytes(value)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    *_JSON_HEADERS,
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _json_bytes(value: object) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
