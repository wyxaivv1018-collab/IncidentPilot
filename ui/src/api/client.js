import {
  API_SCHEMA_VERSION,
  DEMO_SCENARIO_ID,
  approvalRequestBody,
  assertAcceptedRun,
  assertEventStreamEnd,
  assertRunStatus,
  assertTraceEvent,
  traceEventTypes,
} from "../types/api-contract.js";

export class ApiClientError extends Error {
  constructor(message, { code = "CLIENT_ERROR", status = 0, retryable = false } = {}) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.status = status;
    this.retryable = retryable;
  }
}

function runPath(runId, suffix = "") {
  return "/api/v1/runs/" + encodeURIComponent(runId) + suffix;
}

export class IncidentPilotApiClient {
  async startRun() {
    return assertAcceptedRun(
      await this.#request("POST", "/api/v1/runs", {
        scenario_id: DEMO_SCENARIO_ID,
      }),
    );
  }

  async getStatus(runId) {
    return assertRunStatus(await this.#request("GET", runPath(runId)), runId);
  }

  async getEvents(runId, after = 0) {
    const value = await this.#request(
      "GET",
      runPath(runId, "/events?after=" + encodeURIComponent(String(after))),
    );
    if (
      value?.schema_version !== API_SCHEMA_VERSION ||
      value.run_id !== runId ||
      !Array.isArray(value.events) ||
      !Number.isInteger(value.next_after)
    ) {
      throw new ApiClientError("The event snapshot did not match the live run.", {
        code: "EVENT_CONTRACT_INVALID",
      });
    }
    value.events.forEach((event) => assertTraceEvent(event, runId));
    return value;
  }

  async cancelRun(runId) {
    return assertRunStatus(
      await this.#request("POST", runPath(runId, "/cancel"), {}),
      runId,
    );
  }

  async confirmApproval(runId, approval) {
    const body = approvalRequestBody(approval, runId);
    return this.#request(
      "POST",
      runPath(
        runId,
        "/approvals/" + encodeURIComponent(approval.approval_request_id),
      ),
      body,
    );
  }

  async getReport(runId) {
    return this.#request("GET", runPath(runId, "/report"));
  }

  async getMemory(runId) {
    return this.#request("GET", runPath(runId, "/memory"));
  }

  streamEvents(
    runId,
    { after = () => 0, onEvent, onEnd, onConnection, onFailure },
  ) {
    let source = null;
    let closed = false;
    let reconnectTimer = null;
    let reconnectCount = 0;

    const closeSource = () => {
      if (source) source.close();
      source = null;
    };

    const fail = (error) => {
      closed = true;
      closeSource();
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      onFailure(error);
    };

    const open = () => {
      if (closed) return;
      const cursor = after();
      source = new EventSource(
        runPath(runId, "/events/stream?after=" + encodeURIComponent(String(cursor))),
      );
      source.onopen = () => {
        reconnectCount = 0;
        onConnection({ connected: true, after: cursor });
      };
      for (const eventType of traceEventTypes) {
        source.addEventListener(eventType, (message) => {
          try {
            const event = assertTraceEvent(JSON.parse(message.data), runId);
            onEvent(event);
          } catch (error) {
            fail(error);
          }
        });
      }
      source.addEventListener("stream.end", (message) => {
        try {
          const end = assertEventStreamEnd(JSON.parse(message.data), runId);
          closed = true;
          closeSource();
          onEnd(end);
        } catch (error) {
          fail(error);
        }
      });
      source.onerror = () => {
        if (closed) return;
        closeSource();
        reconnectCount += 1;
        onConnection({ connected: false, after: after(), reconnectCount });
        const delay = Math.min(250 * 2 ** Math.min(reconnectCount, 4), 4000);
        reconnectTimer = window.setTimeout(open, delay);
      };
    };

    open();
    return {
      close() {
        closed = true;
        closeSource();
        if (reconnectTimer) window.clearTimeout(reconnectTimer);
      },
    };
  }

  async #request(method, path, body) {
    const options = {
      method,
      headers: { Accept: "application/json" },
      cache: "no-store",
    };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, options);
    } catch {
      throw new ApiClientError("无法连接本地 IncidentPilot 服务。", {
        code: "NETWORK_ERROR",
        retryable: true,
      });
    }
    let value;
    try {
      value = await response.json();
    } catch {
      throw new ApiClientError("本地服务返回了无效 JSON。", {
        code: "INVALID_JSON_RESPONSE",
        status: response.status,
      });
    }
    if (!response.ok) {
      const error = value?.error ?? {};
      throw new ApiClientError(error.message ?? "本地服务拒绝了请求。", {
        code: error.code ?? "API_ERROR",
        status: response.status,
        retryable: error.retryable === true,
      });
    }
    return value;
  }
}
