"""Durable, atomic reservations: lost/failed requests retain their full cost bound."""

from __future__ import annotations

import json
import math
from contextlib import contextmanager
import sqlite3
from pathlib import Path
from uuid import uuid4

MODEL_ID = "nvidia/nemotron-3-super-120b-a12b"
BASE_URL = "https://api.tokenfactory.us-central1.nebius.com/v1/"
INPUT_PER_MILLION = 0.30
OUTPUT_PER_MILLION = 0.90
MAX_INPUT_BOUND = 64000
MAX_OUTPUT_TOKENS = 4096
PRICE_SOURCE = "https://github.com/nebius/token-factory-cookbook/blob/main/agents/agent-cost-comparison-1/agent_cost_comparison_1.py"


class BudgetBlocked(RuntimeError):
    pass


def estimate_request(request: dict) -> tuple[int, float]:
    """Two tokens per UTF-8 byte plus framing allowance, deliberately conservative.

    Includes accumulated messages, tools and system prompt. No cached-token discount.
    Reasoning output is included in the completion limit and counted only once.
    """
    bound = 2 * len(json.dumps(request, ensure_ascii=False).encode("utf8")) + 4096
    if bound > MAX_INPUT_BOUND:
        raise BudgetBlocked("INPUT_BOUND_EXCEEDED")
    return bound, (bound * INPUT_PER_MILLION + MAX_OUTPUT_TOKENS * OUTPUT_PER_MILLION) / 1e6


class BudgetLedger:
    def __init__(self, path: Path, *, limit_usd: float = 0.80, allow_create: bool = True):
        if not 0 < limit_usd <= 1:
            raise ValueError("Budget must be positive and at most the authorized $1")
        self.path = Path(path).resolve()
        created = False
        if allow_create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Only a genuinely new ledger may receive an initial budget.
                with self.path.open("xb"):
                    pass
                created = True
            except FileExistsError:
                pass
        with self._db(initialize=created) as db:
            if created:
                db.execute("CREATE TABLE config (id INTEGER PRIMARY KEY, ceiling REAL)")
                db.execute("INSERT INTO config VALUES (1, ?)", (limit_usd,))
                db.execute("""CREATE TABLE calls (
                    id TEXT PRIMARY KEY, run_id TEXT, upper_usd REAL, actual_usd REAL,
                    input_tokens INTEGER, output_tokens INTEGER, state TEXT)""")
            # A later launch cannot silently raise an already frozen budget ceiling.
            db.execute("UPDATE config SET ceiling = MIN(ceiling, ?) WHERE id=1", (limit_usd,))

    @staticmethod
    def _validate(db):
        def amount(value, maximum=None):
            return (type(value) in (int, float) and math.isfinite(value) and value >= 0
                    and (maximum is None or value <= maximum))

        expected = {
            "config": {"id", "ceiling"},
            "calls": {"id", "run_id", "upper_usd", "actual_usd", "input_tokens",
                      "output_tokens", "state"},
        }
        try:
            for table, columns in expected.items():
                schema = list(db.execute(f"PRAGMA table_info({table})"))
                if ({column[1] for column in schema} != columns
                        or not any(column[1] == "id" and column[5] == 1 for column in schema)):
                    raise BudgetBlocked("BUDGET_STORAGE_INVALID")
            config = db.execute("SELECT id, ceiling FROM config").fetchall()
            if len(config) != 1 or config[0][0] != 1 or not amount(config[0][1], 1):
                raise BudgetBlocked("BUDGET_STORAGE_INVALID")
            rows = db.execute("SELECT id, run_id, upper_usd, actual_usd, input_tokens, "
                              "output_tokens, state FROM calls")
            for request_id, run_id, upper, actual, inputs, outputs, state in rows:
                if (not isinstance(request_id, str) or not request_id
                        or not isinstance(run_id, str) or not run_id
                        or not amount(upper, 0.05) or upper == 0
                        or (actual is not None and not amount(actual))
                        or state not in {"reserved", "usage-received"}
                        or (state == "reserved" and any(value is not None
                                                       for value in (actual, inputs, outputs)))
                        or (state == "usage-received" and (actual is None
                            or any(type(value) is not int or value < 0
                                   for value in (inputs, outputs))))):
                    raise BudgetBlocked("BUDGET_STORAGE_INVALID")
        except sqlite3.Error:
            raise BudgetBlocked("BUDGET_STORAGE_INVALID") from None

    @contextmanager
    def _db(self, *, initialize=False):
        db = None
        try:
            if not self.path.is_file():
                raise BudgetBlocked("BUDGET_STORAGE_MISSING")
            # mode=rw never recreates a ledger lost after startup or between requests.
            db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=10)
            with db:
                if not initialize:
                    self._validate(db)
                yield db
        except (sqlite3.Error, OSError):
            raise BudgetBlocked("BUDGET_STORAGE_UNAVAILABLE") from None
        finally:
            if db is not None:
                db.close()

    def reserve(self, run_id: str, upper_usd: float) -> str:
        if not 0 < upper_usd <= 0.05:
            raise BudgetBlocked("INVALID_REQUEST_BOUND")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            spent = db.execute("SELECT COALESCE(SUM(COALESCE(actual_usd,upper_usd)),0) FROM calls").fetchone()[0]
            ceiling = db.execute("SELECT ceiling FROM config WHERE id=1").fetchone()[0]
            if spent + upper_usd > ceiling:
                raise BudgetBlocked("TOTAL_BUDGET_EXHAUSTED")
            request_id = uuid4().hex
            db.execute("INSERT INTO calls VALUES (?,?,?,NULL,NULL,NULL,'reserved')",
                       (request_id, run_id, upper_usd))
            return request_id

    def settle(self, request_id: str, usage: dict):
        input_tokens, output_tokens = usage.get("inputTokens"), usage.get("outputTokens")
        if (type(input_tokens) is not int or type(output_tokens) is not int
                or input_tokens < 0 or output_tokens < 0):
            return  # Missing usage never releases the reservation.
        cost = (input_tokens * INPUT_PER_MILLION + output_tokens * OUTPUT_PER_MILLION) / 1e6
        with self._db() as db:
            bound = db.execute("SELECT upper_usd FROM calls WHERE id=?", (request_id,)).fetchone()
            if bound is None:
                raise BudgetBlocked("UNKNOWN_RESERVATION")
            db.execute("UPDATE calls SET actual_usd=?,input_tokens=?,output_tokens=?,state='usage-received' WHERE id=?",
                       (cost, input_tokens, output_tokens, request_id))
            if cost > bound[0]:
                db.execute("UPDATE config SET ceiling=0 WHERE id=1")
        if cost > bound[0]:
            raise BudgetBlocked("PROVIDER_USAGE_EXCEEDED_BOUND; further calls disabled")

    def summary(self, run_id: str | None = None):
        with self._db() as db:
            where, args = (" WHERE run_id=?", (run_id,)) if run_id else ("", ())
            rows = db.execute("SELECT upper_usd,actual_usd,input_tokens,output_tokens FROM calls" + where, args).fetchall()
            ceiling = db.execute("SELECT ceiling FROM config WHERE id=1").fetchone()[0]
            total = db.execute("SELECT COALESCE(SUM(COALESCE(actual_usd,upper_usd)),0) FROM calls").fetchone()[0]
        estimated = sum(r[1] or 0 for r in rows)
        unconfirmed = sum(r[0] for r in rows if r[1] is None)
        return {"requests": len(rows), "estimated_usd": round(estimated, 8),
                "unconfirmed_upper_usd": round(unconfirmed, 8),
                "committed_upper_usd": round(estimated + unconfirmed, 8),
                "input_tokens": sum(r[2] or 0 for r in rows),
                "output_tokens": sum(r[3] or 0 for r in rows),
                "ceiling_usd": ceiling,
                "remaining_under_ceiling_usd": round(max(0, ceiling-total), 8),
                "billing_confirmed": False, "price_source": PRICE_SOURCE}
