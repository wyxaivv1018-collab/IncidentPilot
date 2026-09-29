"""Actual HTTP boundary checks, including external-origin and duplicate-run rejection."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from incidentpilot.connected.server import create_server


@pytest.fixture
def server(tmp_path):
    (tmp_path / "ui/src").mkdir(parents=True)
    (tmp_path / "ui/src/connected.html").write_text("owned test UI", encoding="utf8")
    server = create_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", tmp_path
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(base, path, body=None, headers=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body else None,
                                 headers=headers or {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_external_origin_and_unknown_routes_fail_closed(server):
    base, _ = server
    status, body = request(base, "/api/v2/config")
    assert status == 200 and not json.loads(body)["allow_live"]
    status, _ = request(base, "/api/v2/run", {"case": "http-stopped"},
                        {"Content-Type": "application/json", "Origin": "https://example.com"})
    assert status == 403
    assert request(base, "/api/v2/execute", {"action": "anything"})[0] == 404
    assert request(base, "/api/v2/config", headers={"Host": "attacker.invalid"})[0] == 403
    assert request(base, "/../pyproject.toml")[0] == 404


def test_live_is_explicit_and_history_is_marked_recorded(server):
    base, root = server
    assert request(base, "/api/v2/run", {"case": "http-stopped", "mode": "live", "description": "Down"})[0] == 409
    path = root / "runtime/nebius/runs/RUN-NEBIUS-abc/report.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"run_id":"RUN-NEBIUS-abc","mode":"live"}', encoding="utf8")
    status, body = request(base, "/api/v2/history/RUN-NEBIUS-abc")
    assert status == 200 and json.loads(body)["mode"] == "recorded"
    assert request(base, "/api/v2/history/invalid")[0] == 400


@pytest.fixture
def public_server(tmp_path):
    (tmp_path / "ui/src").mkdir(parents=True)
    (tmp_path / "ui/src/connected.html").write_text("owned test UI", encoding="utf8")
    hostname = "judge-demo.example.hf.space"
    server = create_server(
        tmp_path, port=0, public_host=True, public_hostname=hostname
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", hostname
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_public_host_accepts_allowed_host_rejects_attacker(public_server):
    base, hostname = public_server
    status, body = request(
        base,
        "/api/v2/config",
        headers={"Host": hostname},
    )
    assert status == 200 and not json.loads(body)["allow_live"]
    status, body = request(
        base,
        "/api/v2/config",
        headers={"Host": f"{hostname}:443", "Origin": f"https://{hostname}"},
    )
    assert status == 200
    status, _ = request(
        base,
        "/api/v2/config",
        headers={"Host": hostname, "Origin": f"http://{hostname}"},
    )
    assert status == 200
    assert request(base, "/api/v2/config", headers={"Host": "attacker.invalid"})[0] == 403
    assert request(
        base,
        "/api/v2/config",
        headers={"Host": hostname, "Origin": "https://attacker.invalid"},
    )[0] == 403
    # Default loopback Host must not bypass public allowlist.
    assert request(base, "/api/v2/config")[0] == 403
