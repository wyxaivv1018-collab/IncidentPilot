"""Small connector contract and real, exclusively owned loopback test services.

Fault injection lives in the test rig, never in the agent or decision tools.
No connector accepts arbitrary URLs, shell commands, paths or process identifiers.
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol
from uuid import uuid4


class Connector(Protocol):
    system_id: str
    title: str
    actions: dict[str, str]

    def read(self, source: str) -> dict: ...
    def execute(self, action: str) -> dict: ...
    def verify(self) -> dict: ...
    def close(self) -> None: ...


class HttpApplication:
    system_id = "http-app"
    title = "HTTP application"
    actions = {
        "restart_service": "Start or restart this owned HTTP listener; preserves application data.",
        "restore_dependency": "Reconnect the owned application's local catalog dependency.",
    }

    def __init__(self, *, fault: str = "stopped", evidence_available: bool = True):
        self.instance = uuid4().hex
        self._dependency_ready = fault != "dependency"
        self._evidence_available = evidence_available
        self._logs: list[str] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port = 0
        self._lock = threading.RLock()
        self._start()
        if fault == "stopped":
            self._stop()
            self._logs.append("Listener stopped; application process is not accepting connections.")

    def _start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/business":
                    self.send_error(404)
                    return
                with owner._lock:
                    ready = owner._dependency_ready
                payload = {"instance": owner.instance, "items": ["demo-item"] if ready else [],
                           "error": None if ready else "catalog dependency disconnected"}
                data = json.dumps(payload).encode()
                self.send_response(200 if ready else 503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", self._port), Handler)
        self._port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.03}, daemon=True)
        self._thread.start()
        self._logs.append("HTTP listener started on owned loopback endpoint.")

    def _stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=2)
            self._server = None

    def _probe(self):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/business",
                                        timeout=1) as response:
                return {"http_status": response.status, "body": json.load(response)}
        except urllib.error.HTTPError as error:
            return {"http_status": error.code, "body": json.load(error)}
        except (OSError, urllib.error.URLError):
            return {"http_status": None, "error": "connection unavailable"}

    def read(self, source: str):
        if not self._evidence_available:
            return {"available": False, "reason": "Monitoring permission is missing."}
        if source == "logs":
            probe = self._probe()
            return {"available": True, "lines": self._logs[-8:], "request": probe}
        if source == "status":
            return {"available": True, "listener_running": self._server is not None,
                    "business_request": self._probe()}
        raise ValueError("Unknown read source")

    def execute(self, action: str):
        if action == "restart_service":
            self._stop()
            self._start()
        elif action == "restore_dependency":
            with self._lock:
                self._dependency_ready = True
                self._logs.append("Local catalog dependency connection restored.")
        else:
            raise ValueError("Unknown action")
        return {"accepted": True, "operation": action}

    def verify(self):
        if not self._evidence_available:
            return {"status": "UNKNOWN", "detail": "Business probe permission is missing."}
        result = self._probe()
        body = result.get("body", {})
        passed = (result.get("http_status") == 200 and body.get("instance") == self.instance
                  and body.get("items") == ["demo-item"] and body.get("error") is None)
        return {"status": "PASSED" if passed else "FAILED",
                "check": "Fresh HTTP GET /business; status, instance and catalog content", **result}

    def close(self):
        self._stop()


class BackgroundTasks:
    system_id = "background-jobs"
    title = "Background task service"
    actions = {
        "retry_task": "Enqueue the owned failed task; a worker recomputes its output.",
        "release_stale_lock": "Release only this test task's orphaned application lock.",
    }

    def __init__(self, directory: Path, *, fault: str = "transient",
                 evidence_available: bool = True):
        directory.mkdir(parents=True, exist_ok=False)
        self._result_path = directory / "result.json"
        self._job_id = uuid4().hex
        self._input = [7, 11, 13]
        self._locked = fault == "locked"
        self._fail_once = fault == "transient"
        self._evidence_available = evidence_available
        self._status = "QUEUED"
        self._logs: list[str] = []
        self._queue: queue.Queue = queue.Queue()
        self._completed = threading.Event()
        self._lock = threading.RLock()
        self._thread = threading.Thread(target=self._work, daemon=True)
        self._thread.start()
        self._submit()

    def _work(self):
        while self._queue.get() is not None:
            with self._lock:
                self._status = "RUNNING"
                if self._locked:
                    self._status = "FAILED"
                    self._logs.append("Task failed: orphaned lock; no active lock holder.")
                elif self._fail_once:
                    self._fail_once = False
                    self._status = "FAILED"
                    self._logs.append("Task failed: transient dependency timeout; dependency now reachable.")
                else:
                    result = {"job_id": self._job_id, "total": sum(self._input),
                              "input_sha256": hashlib.sha256(json.dumps(self._input).encode()).hexdigest()}
                    self._result_path.write_text(json.dumps(result), encoding="utf8")
                    self._status = "SUCCEEDED"
                    self._logs.append("Task completed; result artifact written by worker.")
            self._completed.set()

    def _submit(self):
        self._completed.clear()
        self._queue.put("run")
        if not self._completed.wait(timeout=2):
            raise TimeoutError("Owned worker did not finish")

    def read(self, source: str):
        if not self._evidence_available:
            return {"available": False, "reason": "Task monitoring permission is missing."}
        with self._lock:
            if source == "logs":
                return {"available": True, "lines": self._logs[-8:]}
            if source == "status":
                return {"available": True, "worker_alive": self._thread.is_alive(),
                        "task_status": self._status, "output_exists": self._result_path.exists()}
        raise ValueError("Unknown read source")

    def execute(self, action: str):
        if action == "retry_task":
            self._submit()
        elif action == "release_stale_lock":
            with self._lock:
                self._locked = False
                self._logs.append("Orphaned task lock released; task not yet rerun.")
        else:
            raise ValueError("Unknown action")
        return {"accepted": True, "operation": action}

    def verify(self):
        if not self._evidence_available:
            return {"status": "UNKNOWN", "detail": "Task output permission is missing."}
        with self._lock:
            try:
                result = json.loads(self._result_path.read_text(encoding="utf8"))
            except (OSError, ValueError):
                result = {}
            expected_hash = hashlib.sha256(json.dumps(self._input).encode()).hexdigest()
            passed = (self._status == "SUCCEEDED" and result.get("job_id") == self._job_id
                      and result.get("total") == sum(self._input)
                      and result.get("input_sha256") == expected_hash)
            return {"status": "PASSED" if passed else "FAILED", "task_status": self._status,
                    "check": "Worker status plus independently checked current-job output", "result": result}

    def close(self):
        self._queue.put(None)
        self._thread.join(timeout=2)


CASES = {
    "http-stopped": {"system": "http-app", "fault": "stopped", "permission": True,
                     "evidence": True, "description": "The application is unavailable."},
    "http-dependency": {"system": "http-app", "fault": "dependency", "permission": True,
                        "evidence": True, "description": "The application is unavailable."},
    "job-transient": {"system": "background-jobs", "fault": "transient", "permission": True,
                      "evidence": True, "description": "The background task failed; its result is missing."},
    "job-locked": {"system": "background-jobs", "fault": "locked", "permission": True,
                   "evidence": True, "description": "The background task failed; its result is missing."},
    "permission-missing": {"system": "http-app", "fault": "stopped", "permission": False,
                           "evidence": True, "description": "The application is unavailable."},
    "evidence-missing": {"system": "background-jobs", "fault": "transient", "permission": True,
                         "evidence": False, "description": "The background task failed; its result is missing."},
}


def create_test_connector(case: str, directory: Path) -> Connector:
    """Test operator setup only. Case names and faults are not given to the agent."""
    spec = CASES[case]
    if spec["system"] == "http-app":
        return HttpApplication(fault=spec["fault"], evidence_available=spec["evidence"])
    return BackgroundTasks(directory, fault=spec["fault"], evidence_available=spec["evidence"])
