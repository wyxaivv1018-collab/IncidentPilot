"""Ledger corruption and in-process file loss must not silently replenish the budget."""

import sqlite3

import pytest

from incidentpilot.connected.budget import BudgetBlocked, BudgetLedger


def test_new_local_ledger_keeps_default_budget(tmp_path):
    path = tmp_path / "runtime" / "nebius" / "budget.sqlite"
    summary = BudgetLedger(path).summary()
    assert path.is_file()
    assert summary["ceiling_usd"] == 0.8 and summary["requests"] == 0


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
