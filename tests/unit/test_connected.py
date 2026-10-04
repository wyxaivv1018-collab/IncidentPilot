"""Real owned-service checks and programmatic boundaries; no paid calls."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from incidentpilot.connected.budget import BudgetBlocked, BudgetLedger, estimate_request
from incidentpilot.connected.connectors import BackgroundTasks, HttpApplication
from incidentpilot.connected.runner import execute_case
from incidentpilot.connected.session import ConnectedSession, read_report


def session(connector, tmp_path, permission=True, mode="offline-test"):
    return ConnectedSession(connector, tmp_path / "runs", permission=permission, mode=mode)


@pytest.mark.parametrize("fault,action", [("stopped", "restart_service"),
                                         ("dependency", "restore_dependency")])
def test_http_real_business_recovery(tmp_path, fault, action):
    connector = HttpApplication(fault=fault)
    try:
        run = session(connector, tmp_path)
        assert run.verify()["status"] == "FAILED"
        evidence = run.read("logs")
        result = run.act(action, [evidence["evidence_id"]], "Current logs support this correction.")
        assert result["action"]["executed"]
        assert result["verification"]["status"] == "PASSED"
        assert connector.verify()["http_status"] == 200
        assert run.report()["verified"]
    finally:
        connector.close()


def test_action_success_does_not_prove_business_recovery(tmp_path):
    connector = HttpApplication(fault="dependency")
    try:
        run = session(connector, tmp_path)
        ref = run.read("status")["evidence_id"]
        result = run.act("restart_service", [ref], "Investigate whether restart helps.")
        assert result["action"]["operation_result"]["accepted"]
        assert result["verification"]["status"] == "FAILED"
        assert not run.report()["verified"]
        changed = run.read("logs")["evidence_id"]
        result = run.act("restore_dependency", [changed], "503 identifies the catalog dependency.")
        assert result["verification"]["status"] == "PASSED"
    finally:
        connector.close()


@pytest.mark.parametrize("fault", ["transient", "locked"])
def test_actual_worker_and_artifact(tmp_path, fault):
    connector = BackgroundTasks(tmp_path / "worker", fault=fault)
    try:
        run = session(connector, tmp_path)
        assert run.verify()["status"] == "FAILED"
        ref = run.read("logs")["evidence_id"]
        if fault == "locked":
            cleared = run.act("release_stale_lock", [ref], "Logs identify an orphaned lock.")
            assert cleared["verification"]["status"] == "FAILED"
        run.act("retry_task", [ref], "Recompute the failed task after inspecting the failure.")
        assert run.report()["verified"]
        # Stale or corrupt output cannot satisfy the business check even with SUCCEEDED state.
        connector._result_path.write_text(json.dumps({"total": 31}), encoding="utf8")
        assert connector.verify()["status"] == "FAILED"
    finally:
        connector.close()


@pytest.mark.parametrize("permission,evidence", [(False, True), (True, False)])
def test_missing_permission_or_evidence_stops_mutation(tmp_path, permission, evidence):
    connector = HttpApplication(evidence_available=evidence)
    try:
        run = session(connector, tmp_path, permission=permission)
        ref = run.read("logs")["evidence_id"]
        run.act("restart_service", [ref], "Try to repair.")
        run.finish("Unavailable", "No permitted repair", "Ask the service owner for access.")
        report = run.report()
        assert report["status"] == "HUMAN_HANDOFF"
        assert report["executed_actions"] == []
        assert not connector._server
    finally:
        connector.close()


def test_untrusted_action_and_foreign_evidence(tmp_path):
    connector = HttpApplication()
    try:
        run = session(connector, tmp_path)
        run.act("restart_service", ["OTHER-RUN-E1"], "Invented evidence")
        ref = run.read("logs")["evidence_id"]
        run.act("run_shell", [ref], "Try an unsupported action")
        assert run.report()["executed_actions"] == []
    finally:
        connector.close()


def test_provider_origin_cannot_be_missing_reused_or_rebound(tmp_path):
    connector = HttpApplication()
    try:
        run = session(connector, tmp_path, mode="live")
        with pytest.raises(PermissionError):
            run.read("status")
        run.register_origin({"toolUseId": "provider-1", "name": "read_evidence", "input": {"source": "logs"}})
        with pytest.raises(PermissionError):
            run.read("status")
        assert run.read("logs")["available"]
        with pytest.raises(PermissionError):
            run.read("logs")
        with pytest.raises(ValueError):
            run.register_origin({"toolUseId": "provider-1", "name": "read_evidence", "input": {}})
    finally:
        connector.close()


def test_cancel_blocks_mutations(tmp_path):
    connector = HttpApplication()
    try:
        run = session(connector, tmp_path)
        ref = run.read("logs")["evidence_id"]
        run.cancelled = True
        with pytest.raises(RuntimeError):
            run.act("restart_service", [ref], "Cancelled")
        assert not run.report()["verified"]
    finally:
        connector.close()


def test_budget_reservations_survive_restart_and_concurrency(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.sqlite", limit_usd=0.025)
    def reserve(_):
        try:
            return ledger.reserve("run", 0.01)
        except BudgetBlocked:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(reserve, range(4)))
    assert len([i for i in ids if i]) == 2
    restarted = BudgetLedger(tmp_path / "budget.sqlite", limit_usd=1)
    assert restarted.summary()["ceiling_usd"] == 0.025
    assert restarted.summary()["unconfirmed_upper_usd"] == 0.02
    restarted.settle(next(i for i in ids if i), {"inputTokens": 100, "outputTokens": 10})
    assert restarted.summary()["unconfirmed_upper_usd"] == 0.01
    with pytest.raises(BudgetBlocked):
        estimate_request({"messages": "x" * 32000})


def test_legacy_reader_does_not_relabel_recording(tmp_path):
    path = tmp_path / "old.json"
    path.write_text('{"run_id":"RUN-C11","status":"RESOLVED"}', encoding="utf8")
    report = read_report(path)
    assert report["format"] == "legacy-v1" and report["mode"] == "recorded"


def test_per_run_budget_reports_shared_remaining(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.sqlite", limit_usd=0.8)
    ledger.reserve("first", 0.02)
    ledger.reserve("second", 0.03)
    assert ledger.summary("first")["committed_upper_usd"] == 0.02
    assert ledger.summary("first")["remaining_under_ceiling_usd"] == 0.75
    assert ledger.summary("second")["remaining_under_ceiling_usd"] == 0.75


@pytest.mark.parametrize("mode,method", [("offline-test", "incidentpilot"), ("live", "sop")])
def test_cancelled_sop_case_preserves_evidence_and_report(tmp_path, monkeypatch, mode, method):
    sessions = []

    def cancel_after_evidence(run):
        sessions.append(run)
        read = run.connector.read

        def read_then_cancel(source):
            result = read(source)
            if source == "logs":
                run.cancelled = True
            return result

        monkeypatch.setattr(run.connector, "read", read_then_cancel)

    report = execute_case("job-transient", tmp_path, mode=mode, method=method,
                          on_session=cancel_after_evidence)
    run = sessions[0]
    saved = json.loads((run.directory / "report.json").read_text(encoding="utf8"))
    events = [json.loads(line) for line in
              (run.directory / "events.jsonl").read_text(encoding="utf8").splitlines()]
    assert saved == report
    assert report["run_id"] == run.run_id
    assert report["status"] == "HUMAN_HANDOFF" and not report["verified"]
    assert report["error"] == "CANCELLED"
    assert report["executed_actions"] == []
    assert report["events"] == events
    assert [event["data"]["source"] for event in events
            if event["type"] == "evidence.read"] == ["status", "logs"]
    assert events[-1]["type"] == "run.error"
    assert events[-1]["data"] == {"category": "CANCELLED"}
    assert not run.connector._thread.is_alive()


@pytest.mark.parametrize("mode,method", [("offline-test", "incidentpilot"), ("live", "sop")])
def test_failed_sop_case_records_safe_error_and_cannot_reuse_pass(tmp_path, monkeypatch,
                                                                mode, method):
    sessions = []
    private_error = "sensitive-test-error-not-for-the-report"

    def fail_final_verification(run):
        sessions.append(run)
        verify = run.connector.verify
        checks = 0

        def verify_then_fail():
            nonlocal checks
            checks += 1
            if checks == 2:
                raise ValueError(private_error)
            return verify()

        monkeypatch.setattr(run.connector, "verify", verify_then_fail)

    report = execute_case("job-transient", tmp_path, mode=mode, method=method,
                          on_session=fail_final_verification)
    run = sessions[0]
    saved_text = (run.directory / "report.json").read_text(encoding="utf8")
    events_text = (run.directory / "events.jsonl").read_text(encoding="utf8")
    assert json.loads(saved_text) == report
    assert report["run_id"] == run.run_id
    assert report["verification"]["status"] == "PASSED"
    assert report["status"] == "HUMAN_HANDOFF" and not report["verified"]
    assert report["executed_actions"] == ["retry_task"]
    assert report["error"] == "ValueError"
    assert report["events"][-1]["type"] == "run.error"
    assert report["events"][-1]["data"] == {"category": "ValueError"}
    assert private_error not in saved_text + events_text
    assert not run.connector._thread.is_alive()
