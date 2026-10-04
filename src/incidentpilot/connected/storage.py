"""Resolve runtime storage without silently replacing a public spending ledger."""

from __future__ import annotations

import os
from pathlib import Path

from incidentpilot.connected.budget import BudgetBlocked, BudgetLedger


def require_persistent_data_dir(path: Path) -> Path:
    """Require an explicitly selected, existing mount point; never create it."""
    path = Path(path)
    if not path.is_absolute():
        raise BudgetBlocked("INCIDENTPILOT_DATA_DIR_MUST_BE_ABSOLUTE")
    path = path.resolve()
    if not path.is_dir() or not os.path.ismount(path):
        raise BudgetBlocked("PUBLIC_LIVE_REQUIRES_PERSISTENT_MOUNT")
    return path


def resolve_runtime(root: Path, *, public_live: bool = False) -> Path:
    configured = os.environ.get("INCIDENTPILOT_DATA_DIR", "").strip()
    if configured:
        runtime = Path(configured)
        if not runtime.is_absolute():
            raise BudgetBlocked("INCIDENTPILOT_DATA_DIR_MUST_BE_ABSOLUTE")
        runtime = runtime.resolve()
    else:
        if public_live:
            raise BudgetBlocked("PUBLIC_LIVE_REQUIRES_INCIDENTPILOT_DATA_DIR")
        runtime = Path(root) / "runtime" / "nebius"
    if public_live:
        runtime = require_persistent_data_dir(runtime)
        BudgetLedger(runtime / "budget.sqlite", allow_create=False)
    return runtime
