"""Loopback-only HTTP bridge for the C09 UI and existing C08 ASGI app."""

from __future__ import annotations

import asyncio
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from incidentpilot.api.asgi import DemoAsgiApp

_MAX_HTTP_BODY_BYTES = 64 * 1024
_LOOPBACK_HOST = "127.0.0.1"


class FullDemoHttpServer(ThreadingHTTPServer):
    """Serve one immutable UI build and one process-local C08 API."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        app: DemoAsgiApp,
        static_root: Path,
    ) -> None:
        self.demo_app = app
        self.static_root = static_root
        super().__init__(server_address, handler_class)


class FullDemoRequestHandler(BaseHTTPRequestHandler):
    """Translate stdlib HTTP requests to ASGI without adding product routes."""

    protocol_version = "HTTP/1.1"
    server_version = "IncidentPilotLocal/1.0"

    @property
    def demo_server(self) -> FullDemoHttpServer:
        server = self.server
        if not isinstance(server, FullDemoHttpServer):
            raise TypeError("handler requires FullDemoHttpServer")
        return server

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch()

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch()

    def log_message(self, format: str, *args: object) -> None:
        message = format % args
        print(f"[http] {self.client_address[0]} {message}", flush=True)

    def _dispatch(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/api/v1/runs" or parsed.path.startswith(
            "/api/v1/runs/"
        ):
            self._serve_asgi(parsed.path, parsed.query)
            return
        if self.command not in {"GET", "HEAD"}:
            self._send_plain(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")
            return
        self._serve_static(parsed.path)

    def _serve_static(self, request_path: str) -> None:
        try:
            decoded = unquote(request_path, errors="strict")
        except UnicodeError:
            self._send_plain(HTTPStatus.BAD_REQUEST, "Invalid path")
            return
        relative = "index.html" if decoded == "/" else decoded.lstrip("/")
        candidate = (self.demo_server.static_root / relative).resolve()
        try:
            candidate.relative_to(self.demo_server.static_root)
        except ValueError:
            self._send_plain(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not candidate.is_file():
            self._send_plain(HTTPStatus.NOT_FOUND, "Not found")
            return
        try:
            body = candidate.read_bytes()
        except OSError:
            self._send_plain(HTTPStatus.INTERNAL_SERVER_ERROR, "Static read failed")
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _serve_asgi(self, path: str, query: str) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_plain(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
            return
        if content_length < 0 or content_length > _MAX_HTTP_BODY_BYTES:
            self._send_plain(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body too large")
            return
        body = self.rfile.read(content_length) if content_length else b""
        request_sent = False
        response_started = False

        async def receive() -> dict[str, Any]:
            nonlocal request_sent
            if request_sent:
                return {"type": "http.disconnect"}
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            nonlocal response_started
            message_type = message.get("type")
            if message_type == "http.response.start":
                if response_started:
                    raise RuntimeError("ASGI response started twice")
                response_started = True
                status = int(message["status"])
                headers = list(message.get("headers", ()))
                content_type = next(
                    (
                        value.decode("latin-1")
                        for key, value in headers
                        if key.lower() == b"content-type"
                    ),
                    "",
                )
                self.send_response(status)
                for key, value in headers:
                    self.send_header(key.decode("latin-1"), value.decode("latin-1"))
                self.send_header("X-Content-Type-Options", "nosniff")
                if content_type.startswith("text/event-stream"):
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                return
            if message_type == "http.response.body":
                if not response_started:
                    raise RuntimeError("ASGI body arrived before response start")
                chunk = message.get("body", b"")
                if chunk:
                    self.wfile.write(chunk)
                    self.wfile.flush()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": self.command,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": query.encode("ascii"),
            "root_path": "",
            "headers": [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in self.headers.items()
            ],
            "client": self.client_address,
            "server": self.server.server_address,
        }
        try:
            asyncio.run(self.demo_server.demo_app(scope, receive, send))
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            if not response_started:
                self._send_plain(HTTPStatus.INTERNAL_SERVER_ERROR, "Local bridge failed safely")
            else:
                self.close_connection = True

    def _send_plain(self, status: HTTPStatus, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def create_full_demo_server(
    app: DemoAsgiApp,
    *,
    static_root: str | Path,
    host: str = _LOOPBACK_HOST,
    port: int = 4173,
) -> FullDemoHttpServer:
    """Create a loopback server; callers own serve_forever and shutdown."""

    if not isinstance(app, DemoAsgiApp):
        raise TypeError("app must be a DemoAsgiApp")
    if host != _LOOPBACK_HOST:
        raise ValueError("the full demo may bind only to 127.0.0.1")
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError("port must be an integer from 0 to 65535")
    root = Path(static_root).resolve()
    if not root.is_dir() or not (root / "index.html").is_file():
        raise ValueError("static_root must contain a built index.html")
    return FullDemoHttpServer(
        (host, port),
        FullDemoRequestHandler,
        app=app,
        static_root=root,
    )


__all__ = [
    "FullDemoHttpServer",
    "FullDemoRequestHandler",
    "create_full_demo_server",
]
