"""Non-generative official model-catalog check. Never print a credential or error body."""

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from incidentpilot.connected.budget import (
    BASE_URL, MODEL_ID, INPUT_PER_MILLION, OUTPUT_PER_MILLION, PRICE_SOURCE,
)


def main():
    root = Path(__file__).resolve().parents[1] / "runtime/nebius/research"
    root.mkdir(parents=True, exist_ok=True)
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "model": MODEL_ID,
              "base_url": BASE_URL, "generative_calls": 0, "paid_calls": 0,
              "price_source": PRICE_SOURCE, "input_per_million_usd": INPUT_PER_MILLION,
              "output_per_million_usd": OUTPUT_PER_MILLION,
              "account_balance_usd": None, "account_expiry": None}
    key = os.environ.get("NEBIUS_API_KEY", "").strip()
    if not key:
        result.update(status="AUTH_BLOCKED", key_present=False)
    else:
        try:
            request = urllib.request.Request(BASE_URL + "models?verbose=true",
                                              headers={"Authorization": "Bearer " + key})
            with urllib.request.urlopen(request, timeout=25) as response:
                catalog = json.load(response)
            match = next((model for model in catalog.get("data", []) if model.get("id") == MODEL_ID), None)
            result.update(status="CATALOG_AVAILABLE" if match else "MODEL_NOT_LISTED",
                          key_present=True, catalog_entry=match)
        except Exception as error:
            result.update(status="CATALOG_BLOCKED", key_present=True,
                          error_category=type(error).__name__, http_status=getattr(error, "code", None))
    (root / "preflight.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print(json.dumps({k: v for k, v in result.items() if k != "catalog_entry"}, indent=2))
    return 0 if result["status"] == "CATALOG_AVAILABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
