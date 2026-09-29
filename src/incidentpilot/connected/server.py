"""Loopback-only v2 UI/API; serial runs share a persistent budget ledger."""

from __future__ import annotations

import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from incidentpilot.connected.budget import BudgetLedger, MODEL_ID
from incidentpilot.connected.connectors import CASES
from incidentpilot.connected.runner import execute_case


def create_server(root: Path, *, port: int = 4180, allow_live: bool = False):
    runtime = root / "runtime" / "nebius"
    ledger = BudgetLedger(runtime / "budget.sqlite")
    state = {"busy": False, "session": None, "report": None, "error": None}
    lock = threading.RLock()
    static = root / "ui" / "src"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send_json(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode("utf8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def trusted(self):
            host = self.headers.get("Host")
            expected = f"127.0.0.1:{self.server.server_port}"
            origin = self.headers.get("Origin")
            return host == expected and (not origin or origin == "http://" + expected)

        def do_GET(self):
            if not self.trusted():
                self.send_json(403, {"error": "LOOPBACK_ORIGIN_REQUIRED"})
                return
            path = urlparse(self.path).path
            if path == "/api/v2/config":
                self.send_json(200, {"allow_live": allow_live,
                    "key_present": bool(os.environ.get("NEBIUS_API_KEY")), "model": MODEL_ID,
                    "budget": ledger.summary(), "cases": CASES})
                return
            if path == "/api/v2/run":
                with lock:
                    session = state["session"]
                    self.send_json(200, {"busy": state["busy"], "report": state["report"],
                        "error": state["error"], "run_id": session.run_id if session else None,
                        "events": list(session.events) if session else [], "budget": ledger.summary()})
                return
            if path == "/api/v2/report":
                self.send_json(200 if state["report"] else 404,
                               state["report"] or {"error": "No completed report"})
                return
            if path == "/api/v2/history":
                reports = []
                for report_path in sorted((runtime / "runs").glob("*/report.json"),
                                          key=lambda path: path.stat().st_mtime_ns):
                    data = json.loads(report_path.read_text(encoding="utf8"))
                    reports.append({k: data[k] for k in ("run_id", "system", "mode", "status")})
                self.send_json(200, reports[-30:])
                return
            if path.startswith("/api/v2/history/"):
                run_id = path.rsplit("/", 1)[-1]
                if not run_id.startswith("RUN-NEBIUS-") or not run_id[11:].isalnum():
                    self.send_json(400, {"error": "Invalid run ID"})
                    return
                report_path = runtime / "runs" / run_id / "report.json"
                if not report_path.is_file():
                    self.send_json(404, {"error": "Report not found"})
                    return
                data = json.loads(report_path.read_text(encoding="utf8"))
                self.send_json(200, {"mode": "recorded", "report": data})
                return
            relative = "connected.html" if path == "/" else path.lstrip("/")
            target = (static / relative).resolve()
            if not target.is_relative_to(static.resolve()) or not target.is_file():
                self.send_error(404)
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", (mimetypes.guess_type(target.name)[0] or "application/octet-stream") + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if not self.trusted() or self.headers.get("Content-Type") != "application/json":
                self.send_json(403, {"error": "SAME_ORIGIN_JSON_REQUIRED"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("object")
            except (ValueError, TypeError):
                self.send_json(400, {"error": "Invalid bounded JSON request"})
                return
            if self.path == "/api/v2/cancel":
                with lock:
                    if state["session"] and state["busy"]:
                        state["session"].cancelled = True
                self.send_json(200, {"cancel_requested": True})
                return
            if self.path != "/api/v2/run":
                self.send_json(404, {"error": "Unknown endpoint"})
                return
            case, mode = body.get("case"), body.get("mode")
            description = body.get("description", "")
            if (case not in CASES or mode not in {"live", "offline-test"}
                    or not isinstance(description, str) or not 1 <= len(description) <= 1500):
                self.send_json(400, {"error": "Select a case, execution mode and brief description"})
                return
            if mode == "live" and (not allow_live or not os.environ.get("NEBIUS_API_KEY")):
                self.send_json(409, {"error": "LIVE_DISABLED_OR_AUTH_BLOCKED"})
                return
            with lock:
                if state["busy"]:
                    self.send_json(409, {"error": "A run is already in progress"})
                    return
                state.update(busy=True, session=None, report=None, error=None)

            def run():
                try:
                    report = execute_case(case, runtime, mode=mode, description=description,
                                          on_session=lambda session: state.update(session=session))
                    with lock:
                        state["report"] = report
                except Exception as exc:
                    state["error"] = type(exc).__name__
                finally:
                    with lock:
                        state["busy"] = False

            threading.Thread(target=run, daemon=True).start()
            self.send_json(202, {"accepted": True})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(root: Path, *, port: int, allow_live: bool):
    server = create_server(root, port=port, allow_live=allow_live)
    print(f"IncidentPilot: http://127.0.0.1:{server.server_port}/", flush=True)
    print(f"Live calls enabled: {allow_live}; model: {MODEL_ID}; development ceiling: $0.80", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
