"""New competition entrypoint; no change to historical C09/C11 launchers."""

import argparse
import json
from pathlib import Path

from incidentpilot.connected.connectors import CASES
from incidentpilot.connected.runner import compare, execute_case


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "run", "compare"])
    parser.add_argument("--case", choices=list(CASES), default="http-stopped")
    parser.add_argument("--method", choices=["incidentpilot", "generic", "sop"], default="incidentpilot")
    parser.add_argument("--live", action="store_true", help="Explicitly allow budgeted Nebius calls")
    parser.add_argument("--port", type=int, default=4180)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    runtime = root / "runtime" / "nebius"
    if args.command == "serve":
        from incidentpilot.connected.server import serve
        serve(root, port=args.port, allow_live=args.live)
    elif args.command == "compare":
        print(compare(runtime, live=args.live))
    else:
        result = execute_case(args.case, runtime, method=args.method,
                              mode="live" if args.live else "offline-test")
        print(json.dumps({k: v for k, v in result.items() if k != "events"}, indent=2))
        return 2 if result["error"] else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
