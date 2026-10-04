"""One-time initialization of a new mounted IncidentPilot data directory."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from incidentpilot.connected.budget import BudgetBlocked, BudgetLedger
from incidentpilot.connected.storage import require_persistent_data_dir

MARKER = ".incidentpilot-storage-initialized"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--ceiling-usd", required=True, type=float)
    args = parser.parse_args(argv)
    if not math.isfinite(args.ceiling_usd) or not 0 < args.ceiling_usd <= 0.8:
        parser.error("--ceiling-usd must be positive and at most 0.80")
    try:
        directory = require_persistent_data_dir(args.data_dir)
        ledger_path = directory / "budget.sqlite"
        marker = directory / MARKER
        if ledger_path.exists() or marker.exists():
            raise BudgetBlocked("STORAGE_ALREADY_INITIALIZED")
        if any(child.name != "lost+found" or not child.is_dir()
               for child in directory.iterdir()):
            raise BudgetBlocked("INITIALIZATION_REQUIRES_EMPTY_DATA_DIRECTORY")
        # Keep this marker even if initialization fails, so retries cannot replenish funds.
        with marker.open("x", encoding="utf8") as stream:
            stream.write("One-time budget initialization attempted. Do not recreate a lost ledger.\n")
        BudgetLedger(ledger_path, limit_usd=args.ceiling_usd)
    except (BudgetBlocked, OSError) as exc:
        reason = str(exc) if isinstance(exc, BudgetBlocked) else type(exc).__name__
        parser.exit(2, f"Storage initialization refused: {reason}\n")
    print(f"Initialized persistent IncidentPilot storage: {directory}")
    print(f"Cumulative budget ceiling: ${args.ceiling_usd:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
