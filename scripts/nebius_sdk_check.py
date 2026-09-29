"""Exercise real Strands/OpenAI adapters against a network-isolated fake SSE transport."""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from incidentpilot.connected import runtime
from incidentpilot.connected.budget import BudgetLedger
from incidentpilot.connected.connectors import HttpApplication
from incidentpilot.connected.session import ConnectedSession


def main():
    root = Path("runtime/nebius/sdk-offline")
    connector = HttpApplication()
    session = ConnectedSession(connector, root, permission=False)
    session.mode = "live"  # Exercise strict provenance; artifact is separately marked MOCK_TRANSPORT.
    requests = []

    def transport(request):
        body = json.loads(request.content)
        assert str(request.url).startswith(runtime.BASE_URL)
        assert body["model"] == runtime.MODEL_ID
        assert "thinking" not in body.get("extra_body", {})
        assert body["max_tokens"] == runtime.MAX_OUTPUT_TOKENS
        requests.append(body)
        calls = [
            ("describe_system", {}),
            ("read_evidence", {"source": "logs"}),
            ("finish_report", {"problem": "The listener is stopped.",
                               "work_done": "Read logs; no mutation permission.",
                               "next_step": "Ask the owner to restore access."}),
        ]
        name, args = calls[len(requests)-1]
        chunks = [
            {"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                {"index": 0, "id": f"provider-mock-{len(requests)}", "type": "function",
                 "function": {"name": name, "arguments": json.dumps(args)}}]}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 30,
                                       "total_tokens": 130}},
        ]
        data = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=data, headers={"Content-Type": "text/event-stream"})

    original_create = runtime.create_model

    def model_factory(session, ledger):
        model = original_create(session, ledger)
        model._custom_client = AsyncOpenAI(api_key="offline-placeholder", max_retries=0,
            base_url=runtime.BASE_URL, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        return model

    try:
        with patch.dict("os.environ", {"NEBIUS_API_KEY": "offline-placeholder"}), patch.object(runtime, "create_model", model_factory):
            result = runtime.run_agent(session, "The application is unavailable.",
                                       BudgetLedger(root / "mock-budget.sqlite"))
        assert len(requests) == 3, result
        assert result["error"] is None, result["error"]
        assert result["status"] == "HUMAN_HANDOFF"
        assert len([e for e in result["events"] if e["type"] == "tool.requested"]) == 3
        assert result["cost"]["input_tokens"] == 300
        output = {"status": "PASS", "mode": "MOCK_TRANSPORT", "paid_calls": 0,
                  "sdk_model_requests": len(requests), "provider_origin_checks": True,
                  "ledger_usage_checks": True, "run_id": session.run_id}
        (root / "check.json").write_text(json.dumps(output, indent=2), encoding="utf8")
        # This mock transport artifact must never appear as actual Nebius evidence.
        result["mode"] = "offline-sdk-test"
        result["cost"]["billing_confirmed"] = False
        (session.directory / "report.json").write_text(json.dumps(result, indent=2), encoding="utf8")
        print(json.dumps(output))
    finally:
        connector.close()


if __name__ == "__main__":
    main()
