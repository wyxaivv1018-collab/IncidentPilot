"""Public live storage must retain its ledger or stop; no paid calls or real mounts."""

import json
import sqlite3
from pathlib import Path

import pytest

from incidentpilot.connected import storage
from incidentpilot.connected.budget import BudgetBlocked, BudgetLedger
from scripts.init_nebius_storage import MARKER, main as initialize_storage


def mounted(monkeypatch, directory):
    monkeypatch.setattr(storage.os.path, "ismount", lambda path: Path(path) == directory)
    monkeypatch.setenv("INCIDENTPILOT_DATA_DIR", str(directory))


def test_local_default_keeps_existing_layout_and_initialization(tmp_path, monkeypatch):
    monkeypatch.delenv("INCIDENTPILOT_DATA_DIR", raising=False)
    runtime = storage.resolve_runtime(tmp_path)
    assert runtime == tmp_path / "runtime" / "nebius"
    assert BudgetLedger(runtime / "budget.sqlite").summary()["ceiling_usd"] == 0.8


def test_explicit_local_data_directory_does_not_require_a_mount(tmp_path, monkeypatch):
    directory = tmp_path / "chosen-local-data"
    monkeypatch.setenv("INCIDENTPILOT_DATA_DIR", str(directory))
    monkeypatch.setattr(storage.os.path, "ismount", lambda path: False)
    assert storage.resolve_runtime(tmp_path / "repo") == directory


@pytest.mark.parametrize("public_live", [False, True])
def test_relative_data_directory_is_rejected(tmp_path, monkeypatch, public_live):
    monkeypatch.setenv("INCIDENTPILOT_DATA_DIR", "relative-data")
    with pytest.raises(BudgetBlocked, match="MUST_BE_ABSOLUTE"):
        storage.resolve_runtime(tmp_path, public_live=public_live)


def test_public_live_requires_explicit_data_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("INCIDENTPILOT_DATA_DIR", raising=False)
    with pytest.raises(BudgetBlocked, match="REQUIRES_INCIDENTPILOT_DATA_DIR"):
        storage.resolve_runtime(tmp_path, public_live=True)
    assert not (tmp_path / "runtime").exists()


def test_public_live_rejects_unmounted_directory_even_with_valid_ledger(tmp_path, monkeypatch):
    BudgetLedger(tmp_path / "budget.sqlite")
    monkeypatch.setenv("INCIDENTPILOT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(storage.os.path, "ismount", lambda path: False)
    with pytest.raises(BudgetBlocked, match="REQUIRES_PERSISTENT_MOUNT"):
        storage.resolve_runtime(tmp_path / "repo", public_live=True)


def test_public_live_requires_initialized_mounted_ledger(tmp_path, monkeypatch):
    mounted(monkeypatch, tmp_path)
    with pytest.raises(BudgetBlocked, match="BUDGET_STORAGE_MISSING"):
        storage.resolve_runtime(tmp_path / "repo", public_live=True)
    assert not (tmp_path / "budget.sqlite").exists()


def test_missing_ledger_without_creation_does_not_create_parent(tmp_path):
    directory = tmp_path / "missing-directory"
    with pytest.raises(BudgetBlocked, match="BUDGET_STORAGE_MISSING"):
        BudgetLedger(directory / "budget.sqlite", allow_create=False)
    assert not directory.exists()


@pytest.mark.parametrize("damage", ["empty", "not-sqlite", "missing-calls", "missing-config",
                                    "invalid-ceiling", "invalid-reservation", "invalid-schema"])
def test_invalid_existing_ledger_is_never_reinitialized(tmp_path, damage):
    path = tmp_path / "budget.sqlite"
    if damage == "empty":
        path.touch()
    elif damage == "not-sqlite":
        path.write_bytes(b"invalid sqlite ledger")
    else:
        BudgetLedger(path).reserve("existing-run", 0.01)
        with sqlite3.connect(path) as db:
            db.execute({
                "missing-calls": "DROP TABLE calls",
                "missing-config": "DELETE FROM config",
                "invalid-ceiling": "UPDATE config SET ceiling=-1",
                "invalid-reservation": "UPDATE calls SET upper_usd=NULL",
                "invalid-schema": "ALTER TABLE calls RENAME COLUMN upper_usd TO wrong_name",
            }[damage])
    before = path.read_bytes()
    for allow_create in (False, True):
        with pytest.raises(BudgetBlocked, match="BUDGET_STORAGE_INVALID"):
            BudgetLedger(path, allow_create=allow_create)
        assert path.read_bytes() == before


@pytest.mark.parametrize("operation", ["summary", "reserve", "settle"])
def test_existing_ledger_cannot_recreate_file_lost_between_calls(tmp_path, operation):
    path = tmp_path / "budget.sqlite"
    ledger = BudgetLedger(path)
    request = ledger.reserve("existing-run", 0.01)
    path.unlink()
    invoke = {
        "summary": lambda: ledger.summary(),
        "reserve": lambda: ledger.reserve("new-run", 0.01),
        "settle": lambda: ledger.settle(request, {"inputTokens": 10, "outputTokens": 10}),
    }[operation]
    with pytest.raises(BudgetBlocked, match="BUDGET_STORAGE_MISSING"):
        invoke()
    with pytest.raises(BudgetBlocked, match="BUDGET_STORAGE_MISSING"):
        BudgetLedger(path, allow_create=False)
    assert not path.exists()


def test_schema_lost_after_startup_fails_closed(tmp_path):
    path = tmp_path / "budget.sqlite"
    ledger = BudgetLedger(path)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE calls")
    with pytest.raises(BudgetBlocked, match="BUDGET_STORAGE_INVALID"):
        ledger.reserve("new-run", 0.01)


def test_deployments_share_mounted_budget_and_history(tmp_path, monkeypatch):
    directory = tmp_path / "persistent-data"
    directory.mkdir()
    mounted(monkeypatch, directory)
    assert initialize_storage(["--data-dir", str(directory), "--ceiling-usd", "0.04"]) == 0
    first = storage.resolve_runtime(tmp_path / "first-deployment", public_live=True)
    ledger = BudgetLedger(first / "budget.sqlite", allow_create=False)
    ledger.reserve("prior-run", 0.03)
    history = first / "runs" / "prior-run" / "report.json"
    history.parent.mkdir(parents=True)
    history.write_text(json.dumps({"run_id": "prior-run"}), encoding="utf8")

    second = storage.resolve_runtime(tmp_path / "next-deployment", public_live=True)
    restarted = BudgetLedger(second / "budget.sqlite", allow_create=False)
    assert first == second == directory
    assert restarted.summary()["unconfirmed_upper_usd"] == 0.03
    assert restarted.summary()["ceiling_usd"] == 0.04
    with pytest.raises(BudgetBlocked, match="TOTAL_BUDGET_EXHAUSTED"):
        restarted.reserve("next-run", 0.02)
    assert json.loads((second / "runs" / "prior-run" / "report.json").read_text()) == {
        "run_id": "prior-run"}
    assert not (tmp_path / "first-deployment").exists()
    assert not (tmp_path / "next-deployment").exists()


@pytest.mark.parametrize("ceiling", ["0", "-1", "0.81", "nan", "inf"])
def test_initializer_rejects_invalid_ceiling(tmp_path, monkeypatch, ceiling):
    mounted(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as failure:
        initialize_storage(["--data-dir", str(tmp_path), "--ceiling-usd", ceiling])
    assert failure.value.code == 2
    assert not (tmp_path / "budget.sqlite").exists()
    assert not (tmp_path / MARKER).exists()


def test_initializer_requires_mount(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.os.path, "ismount", lambda path: False)
    with pytest.raises(SystemExit) as failure:
        initialize_storage(["--data-dir", str(tmp_path), "--ceiling-usd", "0.8"])
    assert failure.value.code == 2
    assert not (tmp_path / "budget.sqlite").exists()


@pytest.mark.parametrize("lose_ledger", [False, True])
def test_initializer_cannot_replenish_an_initialized_mount(tmp_path, monkeypatch, lose_ledger):
    mounted(monkeypatch, tmp_path)
    args = ["--data-dir", str(tmp_path), "--ceiling-usd", "0.03"]
    assert initialize_storage(args) == 0
    path = tmp_path / "budget.sqlite"
    BudgetLedger(path, allow_create=False).reserve("prior-run", 0.02)
    if lose_ledger:
        path.unlink()
    with pytest.raises(SystemExit) as failure:
        initialize_storage(args)
    assert failure.value.code == 2
    assert (tmp_path / MARKER).is_file()
    if lose_ledger:
        assert not path.exists()
    else:
        assert BudgetLedger(path, allow_create=False).summary()["unconfirmed_upper_usd"] == 0.02


def test_initializer_requires_empty_directory_but_allows_lost_found(tmp_path, monkeypatch):
    mounted(monkeypatch, tmp_path)
    (tmp_path / "lost+found").mkdir()
    other = tmp_path / "existing-history.json"
    other.write_text("{}", encoding="utf8")
    args = ["--data-dir", str(tmp_path), "--ceiling-usd", "0.03"]
    with pytest.raises(SystemExit) as failure:
        initialize_storage(args)
    assert failure.value.code == 2
    assert not (tmp_path / MARKER).exists()
    other.unlink()
    assert initialize_storage(args) == 0
