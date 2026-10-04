"""Actual HTTP boundary checks, including external-origin and duplicate-run rejection."""

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from incidentpilot.connected.server import create_server


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.delenv("INCIDENTPILOT_DATA_DIR", raising=False)
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
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
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
def public_server(tmp_path, monkeypatch):
    monkeypatch.delenv("INCIDENTPILOT_DATA_DIR", raising=False)
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


def test_pending_run_mode_and_cancel_survive_session_initialization(server, monkeypatch):
    import incidentpilot.connected.server as server_module

    base, root = server
    entered, release = threading.Event(), threading.Event()
    original = server_module.execute_case

    def delayed_case(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(server_module, "execute_case", delayed_case)
    try:
        status, _ = request(base, "/api/v2/run", {
            "case": "http-stopped", "mode": "offline-test", "description": "Down",
        })
        assert status == 202 and entered.wait(2)
        state = json.loads(request(base, "/api/v2/run")[1])
        assert state["busy"] and state["run_id"] is None
        assert state["mode"] == "offline-test"
        assert request(base, "/api/v2/cancel", {})[0] == 200
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = json.loads(request(base, "/api/v2/run")[1])
        if not state["busy"]:
            break
        time.sleep(0.02)
    assert not state["busy"]
    assert state["report"]["error"] == "CANCELLED"
    assert state["report"]["executed_actions"] == []
    rows = json.loads(request(base, "/api/v2/history")[1])
    assert rows[-1]["run_id"] == state["report"]["run_id"]
    assert (root / "runtime/nebius/runs" / rows[-1]["run_id"] / "report.json").is_file()



def test_public_live_deployments_preserve_and_inject_the_ledger(tmp_path, monkeypatch):
    import incidentpilot.connected.runner as runner_module
    import incidentpilot.connected.server as server_module
    from incidentpilot.connected import storage
    from incidentpilot.connected.budget import BudgetBlocked, BudgetLedger

    directory = tmp_path / "persistent-data"
    path = directory / "budget.sqlite"
    BudgetLedger(path, limit_usd=0.05).reserve("prior-run", 0.01)
    report_path = directory / "runs" / "RUN-NEBIUS-prior" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({"run_id": "RUN-NEBIUS-prior", "system": "http-app",
                                     "mode": "live", "status": "HUMAN_HANDOFF"}), encoding="utf8")
    monkeypatch.setenv("INCIDENTPILOT_DATA_DIR", str(directory))
    monkeypatch.setenv("NEBIUS_API_KEY", "unused-test-key")
    monkeypatch.setattr(storage.os.path, "ismount", lambda value: value == directory)
    server_ledgers, run_ledgers, failures = [], [], []
    finished = threading.Event()

    def existing_ledger(*args, **kwargs):
        assert kwargs["allow_create"] is False
        ledger = BudgetLedger(*args, **kwargs)
        server_ledgers.append(ledger)
        return ledger

    def fake_agent(session, description, ledger):
        run_ledgers.append(ledger)
        ledger.reserve(session.run_id, 0.01)
        return session.report(cost=ledger.summary(session.run_id))

    execute = server_module.execute_case

    def observed_case(*args, **kwargs):
        try:
            assert kwargs["budget_ledger"] is server_ledgers[-1]
            return execute(*args, **kwargs)
        except Exception as exc:
            failures.append(exc)
            raise
        finally:
            finished.set()

    monkeypatch.setattr(server_module, "BudgetLedger", existing_ledger)
    monkeypatch.setattr(server_module, "execute_case", observed_case)
    monkeypatch.setattr(runner_module, "run_agent", fake_agent)
    hostname = "persistent-demo.example"
    headers = {"Host": hostname, "Content-Type": "application/json"}
    request_body = {"case": "job-transient", "mode": "live", "description": "Task failed"}
    for deployment in range(2):
        root = tmp_path / f"deployment-{deployment}"
        instance = create_server(root, port=0, allow_live=True, public_host=True,
                                 public_hostname=hostname)
        thread = threading.Thread(target=instance.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{instance.server_port}"
        try:
            status, content = request(base, "/api/v2/config", headers=headers)
            assert status == 200
            budget = json.loads(content)["budget"]
            assert budget["requests"] == deployment + 1
            assert budget["ceiling_usd"] == 0.05
            assert budget["unconfirmed_upper_usd"] == round(0.01 * (deployment + 1), 8)
            rows = json.loads(request(base, "/api/v2/history", headers=headers)[1])
            assert len(rows) == deployment + 1
            assert any(row["run_id"] == "RUN-NEBIUS-prior" for row in rows)
            finished.clear()
            assert request(base, "/api/v2/run", request_body, headers)[0] == 202
            assert finished.wait(3)
            assert not failures
            assert run_ledgers[-1] is server_ledgers[-1]
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                state = json.loads(request(base, "/api/v2/run", headers=headers)[1])
                if not state["busy"]:
                    break
                time.sleep(0.01)
            assert not state["busy"] and state["report"]
            assert state["budget"]["requests"] == deployment + 2
            assert not (root / "runtime").exists()
            if deployment == 1:
                path.unlink()
                finished.clear()
                assert request(base, "/api/v2/run", request_body, headers)[0] == 202
                assert finished.wait(3)
                assert len(failures) == 1 and isinstance(failures[0], BudgetBlocked)
                assert run_ledgers[-1] is server_ledgers[-1]
                assert len(server_ledgers) == 2
                assert not path.exists()
        finally:
            instance.shutdown()
            instance.server_close()
            thread.join(timeout=2)
    with pytest.raises(BudgetBlocked, match="BUDGET_STORAGE_MISSING"):
        create_server(tmp_path / "third-deployment", port=0, allow_live=True,
                      public_host=True, public_hostname=hostname)
    assert not path.exists()
