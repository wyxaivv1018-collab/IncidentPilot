export const API_SCHEMA_VERSION = "1.0";
export const DEMO_SCENARIO_ID = "order-sync-double-fault";

export const traceEventTypes = Object.freeze([
  "run.started",
  "model_turn.started",
  "model_turn.completed",
  "tool.requested",
  "tool.result",
  "policy.decision",
  "action.executed",
  "post_action_verification.started",
  "verification.result",
  "verification.observation_delivered",
  "agent.summary",
  "run.budget_exceeded",
  "run.completed",
  "run.failed",
  "run.timeout",
]);

export const activeRunStates = Object.freeze([
  "STARTING",
  "RUNNING",
  "CANCEL_REQUESTED",
]);

export const terminalRunStates = Object.freeze([
  "CANCELLED",
  "RESOLVED",
  "UNRESOLVED",
  "FAILED",
  "TIMEOUT",
  "BUDGET_EXCEEDED",
  "AUTH_BLOCKED",
  "RUNTIME_BLOCKED",
]);

const knownRunStates = new Set([...activeRunStates, ...terminalRunStates]);
const knownTraceEventTypes = new Set(traceEventTypes);
const safeIdentifier = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

function requireObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(label + " must be an object.");
  }
  return value;
}

function requireString(value, label) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new TypeError(label + " must be a non-empty string.");
  }
  return value;
}

function requireArray(value, label) {
  if (!Array.isArray(value)) {
    throw new TypeError(label + " must be an array.");
  }
  return value;
}

function requireRunId(value, label = "run_id") {
  const runId = requireString(value, label);
  if (!safeIdentifier.test(runId)) {
    throw new TypeError(label + " is not a safe identifier.");
  }
  return runId;
}

function requireSchema(value, expected, label) {
  if (value !== expected) {
    throw new TypeError(label + " has an unsupported schema version.");
  }
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function stateFacts(state = {}) {
  const facts = [];
  for (const [label, key] of [
    ["worker", "worker_status"],
    ["sync job", "sync_job_status"],
    ["cache lock", "cache_lock"],
    ["database", "database_status"],
  ]) {
    if (typeof state[key] === "string") {
      facts.push({ label, value: state[key] });
    }
  }
  return facts;
}

export function assertAcceptedRun(value) {
  const accepted = requireObject(value, "run start response");
  requireSchema(accepted.schema_version, API_SCHEMA_VERSION, "run start response");
  requireRunId(accepted.run_id);
  if (accepted.scenario_id !== DEMO_SCENARIO_ID || accepted.status !== "STARTING") {
    throw new TypeError("The backend accepted an unexpected run contract.");
  }
  requireObject(accepted.links, "run links");
  return accepted;
}

export function assertPendingApproval(value, runId) {
  const approval = requireObject(value, "pending approval");
  requireString(approval.approval_request_id, "approval_request_id");
  if (approval.run_id !== runId || approval.status !== "PENDING") {
    throw new TypeError("Pending approval does not belong to the active run.");
  }
  requireString(approval.action, "approval action");
  requireString(approval.target, "approval target");
  const scope = requireArray(approval.scope, "approval scope");
  if (scope.length === 0 || scope.some((item) => typeof item !== "string" || !item)) {
    throw new TypeError("Approval scope is invalid.");
  }
  const argumentsValue = requireObject(approval.arguments, "approval arguments");
  if (
    Object.entries(argumentsValue).some(
      ([key, item]) => !key || typeof item !== "string" || !item,
    )
  ) {
    throw new TypeError("Approval arguments are invalid.");
  }
  if (approval.risk !== "HIGH" || approval.single_use !== true) {
    throw new TypeError("Only an exact, single-use HIGH approval may be shown.");
  }
  requireString(approval.expires_at, "approval expiry");
  return approval;
}

export function approvalRequestBody(approval, runId) {
  const canonical = assertPendingApproval(approval, runId);
  return {
    action: canonical.action,
    target: canonical.target,
    scope: [...canonical.scope],
    arguments: { ...canonical.arguments },
  };
}

export function assertRunStatus(value, expectedRunId) {
  const status = requireObject(value, "run status");
  requireSchema(status.schema_version, API_SCHEMA_VERSION, "run status");
  const runId = requireRunId(status.run_id);
  if (runId !== expectedRunId || !knownRunStates.has(status.status)) {
    throw new TypeError("Run status does not match the active run contract.");
  }
  requireString(status.detail, "run status detail");
  const pending = requireArray(status.pending_approvals, "pending approvals");
  pending.forEach((approval) => assertPendingApproval(approval, runId));
  if (pending.length > 1) {
    throw new TypeError("The narrow demo cannot expose multiple pending approvals.");
  }
  return status;
}

export function assertTraceEvent(value, expectedRunId) {
  const event = requireObject(value, "trace event");
  requireRunId(event.run_id, "event run_id");
  if (event.run_id !== expectedRunId) {
    throw new TypeError("Trace event belongs to another run.");
  }
  requireString(event.event_id, "event_id");
  if (!Number.isInteger(event.sequence) || event.sequence < 1) {
    throw new TypeError("Trace event sequence must be a positive integer.");
  }
  if (!knownTraceEventTypes.has(event.event_type)) {
    throw new TypeError("Trace event type is not part of the reviewed contract.");
  }
  requireString(event.occurred_at, "event occurred_at");
  requireString(event.summary, "event summary");
  requireObject(event.payload, "event payload");
  requireArray(event.related_event_ids, "related event ids");
  requireSchema(event.schema_version, "1.1", "trace event");
  return event;
}

export function appendLiveTraceEvent(events, eventSignatures, event) {
  const signature = JSON.stringify(event);
  if (eventSignatures.has(event.sequence)) {
    if (eventSignatures.get(event.sequence) !== signature) {
      throw new Error("同一 sequence 的事件内容发生变化，实时流已被拒绝。");
    }
    return false;
  }
  const expected = (events.at(-1)?.sequence ?? 0) + 1;
  if (event.sequence !== expected) {
    throw new Error("实时事件存在序号缺口：期待 " + expected + "，收到 " + event.sequence + "。");
  }
  events.push(event);
  eventSignatures.set(event.sequence, signature);
  return true;
}

export function assertEventStreamEnd(value, expectedRunId) {
  const end = requireObject(value, "stream end");
  requireSchema(end.schema_version, API_SCHEMA_VERSION, "stream end");
  if (end.run_id !== expectedRunId || !terminalRunStates.includes(end.status)) {
    throw new TypeError("Stream ended without a matching terminal run state.");
  }
  if (!Number.isInteger(end.next_after) || end.next_after < 0) {
    throw new TypeError("Stream end cursor is invalid.");
  }
  return end;
}

const terminalTraceEventTypes = new Set([
  "run.completed",
  "run.failed",
  "run.timeout",
]);

function sealedTerminalEvent(rawEvents, status) {
  if (!Array.isArray(rawEvents) || rawEvents.length === 0 || !status) return null;
  const terminal = rawEvents.at(-1);
  if (
    !terminalTraceEventTypes.has(terminal.event_type) ||
    rawEvents
      .slice(0, -1)
      .some((event) => terminalTraceEventTypes.has(event.event_type)) ||
    terminal.run_id !== status.run_id ||
    terminal.payload?.status !== status.status
  ) {
    return null;
  }
  return terminal;
}

export function assertSealedTerminalTrace(rawEvents, end, status) {
  const terminal = sealedTerminalEvent(rawEvents, status);
  if (!terminal) {
    throw new TypeError("终态事件必须是封口轨迹的最后一条事件。");
  }
  if (
    end.run_id !== status.run_id ||
    end.status !== status.status ||
    end.next_after !== terminal.sequence ||
    status.event_count !== rawEvents.length ||
    status.last_event_id !== terminal.event_id
  ) {
    throw new TypeError("SSE 终止游标或状态与封口终态不一致。");
  }
  return terminal;
}

function assertArtifact(value, type, runId) {
  const artifact = requireObject(value, type);
  requireSchema(artifact.schema_version, "1.0", type);
  if (artifact.run_id !== runId || artifact.scenario_id !== DEMO_SCENARIO_ID) {
    throw new TypeError(type + " does not belong to the completed live run.");
  }
  requireArray(artifact.evidence_event_ids, type + " evidence ids");
  requireArray(artifact.actions, type + " actions");
  requireArray(artifact.confirmed_root_causes, type + " root causes");
  return artifact;
}

export function assertArtifactPair(reportResponse, memoryResponse, runId) {
  const reportEnvelope = requireObject(reportResponse, "report response");
  const memoryEnvelope = requireObject(memoryResponse, "memory response");
  requireSchema(reportEnvelope.schema_version, API_SCHEMA_VERSION, "report response");
  requireSchema(memoryEnvelope.schema_version, API_SCHEMA_VERSION, "memory response");
  if (reportEnvelope.run_id !== runId || memoryEnvelope.run_id !== runId) {
    throw new TypeError("Artifact envelopes do not belong to the active run.");
  }
  const report = assertArtifact(reportEnvelope.report, "incident report", runId);
  const memory = assertArtifact(memoryEnvelope.memory, "incident memory", runId);
  const reportVerification = requireObject(report.outcome, "report outcome");
  const memoryResolution = requireObject(memory.resolution, "memory resolution");
  if (
    report.final_status !== memory.final_status ||
    reportVerification.verification_event_id !== memoryResolution.verification_event_id ||
    reportVerification.verification_status !== memoryResolution.verification_status
  ) {
    throw new TypeError("Report and Memory do not describe the same verified outcome.");
  }
  return { report, memory };
}

function findActionForVerification(eventsById, verification) {
  const actionEventId = verification.payload.verified_action_event_id;
  const actionEvent = actionEventId ? eventsById.get(actionEventId) : null;
  if (!actionEvent || actionEvent.event_type !== "action.executed") return {};
  const result = actionEvent.payload.action_result;
  if (!result || typeof result !== "object") return {};
  const request = result.request;
  if (!request || typeof request !== "object") return {};
  const policyEvent = actionEvent.payload.policy_event_id
    ? eventsById.get(actionEvent.payload.policy_event_id)
    : null;
  const findings = Array.isArray(result.new_findings) ? result.new_findings : [];
  return { actionEvent, result, request, policyEvent, finding: findings[0] };
}

function mapEnvironmentEvent(event) {
  const data = event.payload.data;
  const logs = Array.isArray(data.visible_logs) ? data.visible_logs : [];
  return {
    eventId: event.event_id,
    sequence: event.sequence,
    occurredAt: event.occurred_at,
    eventType: event.event_type,
    phase: "investigate",
    tone: "info",
    kicker: "实时调查",
    title: "先读取环境事实",
    summary: event.summary,
    evidenceIds: unique([...event.related_event_ids, event.event_id]),
    facts: [
      ...stateFacts(data),
      ...logs.slice(0, 2).map((item) => ({
        label: "可见证据",
        value: String(item.code ?? "unknown"),
      })),
    ],
  };
}

function mapSummaryEvent(event) {
  const kind = event.payload.kind;
  const isReplan = kind === "replan";
  return {
    eventId: event.event_id,
    sequence: event.sequence,
    occurredAt: event.occurred_at,
    eventType: event.event_type,
    phase: isReplan ? "replan" : "plan",
    tone: isReplan ? "replan" : "plan",
    kicker: isReplan ? "基于证据重规划" : "模型初始计划",
    title: isReplan ? "新证据改变了后续计划" : "模型给出恢复计划",
    summary: event.summary,
    evidenceIds: unique([
      ...(Array.isArray(event.payload.evidence_event_ids)
        ? event.payload.evidence_event_ids
        : []),
      ...event.related_event_ids,
      event.event_id,
    ]),
    facts: [
      { label: "决策来源", value: "provider-originated " + kind },
      { label: "模型轮次", value: event.model_turn_id ?? "unknown" },
    ],
  };
}

function mapVerificationEvent(event, eventsById, afterReplan) {
  const { actionEvent, result, request, policyEvent, finding } =
    findActionForVerification(eventsById, event);
  const verification = event.payload.verification ?? {};
  const status = event.payload.status;
  const passed = status === "passed";
  const hasNovelEvidence = finding && typeof finding.code === "string";
  let phase = passed ? "verified" : "first-repair";
  let kicker = passed ? "权威恢复证明" : "动作后权威验证";
  let title = passed ? "权威验证通过" : "动作完成，但验证未通过";
  if (!passed && hasNovelEvidence) {
    phase = "failed-repair";
    kicker = "修复未成功 · 暴露新证据";
    title = "验证未通过，并出现新证据 " + finding.code;
  } else if (!passed && afterReplan) {
    phase = "recovery";
    kicker = "按新计划继续恢复";
    title = "仍等待最终权威通过";
  }
  const detail =
    typeof verification.detail === "string" ? verification.detail : event.summary;
  const actionDetail = result && typeof result.detail === "string" ? result.detail : "";
  const state = verification.state ?? result?.state ?? {};
  const evidence = Array.isArray(verification.evidence) ? verification.evidence : [];
  return {
    eventId: event.event_id,
    sequence: event.sequence,
    occurredAt: event.occurred_at,
    eventType: event.event_type,
    phase,
    tone: passed ? "success" : hasNovelEvidence ? "danger" : "warning",
    kicker,
    title,
    summary: [actionDetail, detail].filter(Boolean).join(" "),
    evidenceIds: unique([
      ...event.related_event_ids,
      actionEvent?.event_id,
      policyEvent?.event_id,
      event.event_id,
    ]),
    action: request
      ? {
          name: request.action,
          target: request.target,
          risk: policyEvent?.payload?.risk ?? "UNKNOWN",
          policyDecision: policyEvent?.payload?.decision ?? "UNKNOWN",
          outcome: result?.outcome ?? "unknown",
        }
      : undefined,
    verification: {
      eventId: event.event_id,
      status,
      authoritative: true,
      detail,
    },
    newEvidence: hasNovelEvidence
      ? {
          code: finding.code,
          findingId: finding.finding_id ?? "unknown",
          source: finding.source ?? "unknown",
        }
      : undefined,
    facts: [
      ...stateFacts(state),
      ...evidence.slice(0, 2).map((item) => ({
        label: "权威证据",
        value: String(item.code ?? "unknown"),
      })),
    ],
  };
}

function mapTerminalEvent(event) {
  const status = String(event.payload.status ?? "FAILED").toUpperCase();
  const verified =
    event.event_type === "run.completed" && event.payload.verified_recovery === true;
  return {
    eventId: event.event_id,
    sequence: event.sequence,
    occurredAt: event.occurred_at,
    eventType: event.event_type,
    phase: "published",
    tone: verified ? "success" : "danger",
    kicker: verified ? "运行结果" : "安全终止",
    title: verified ? "同一轨迹的报告与记忆可以读取" : "运行未建立恢复结论",
    summary: event.summary,
    evidenceIds: unique([...event.related_event_ids, event.event_id]),
    terminal: { status, verifiedRecovery: verified },
    facts: [
      { label: "运行结论", value: status },
      { label: "恢复已验证", value: String(verified) },
    ],
  };
}

export function liveTimeline(rawEvents) {
  const eventsById = new Map(rawEvents.map((event) => [event.event_id, event]));
  const timeline = [];
  let environmentIncluded = false;
  let afterReplan = false;
  for (const event of rawEvents) {
    if (
      !environmentIncluded &&
      event.event_type === "tool.result" &&
      event.payload.data &&
      typeof event.payload.data === "object" &&
      typeof event.payload.data.incident_id === "string"
    ) {
      timeline.push(mapEnvironmentEvent(event));
      environmentIncluded = true;
      continue;
    }
    if (
      event.event_type === "agent.summary" &&
      ["plan", "replan"].includes(event.payload.kind)
    ) {
      timeline.push(mapSummaryEvent(event));
      if (event.payload.kind === "replan") afterReplan = true;
      continue;
    }
    if (event.event_type === "verification.result") {
      timeline.push(mapVerificationEvent(event, eventsById, afterReplan));
      continue;
    }
    if (["run.completed", "run.failed", "run.timeout", "run.budget_exceeded"].includes(event.event_type)) {
      timeline.push(mapTerminalEvent(event));
    }
  }
  return timeline;
}

export function hasVerifiedRecovery(status, rawEvents, artifacts) {
  if (!status || status.status !== "RESOLVED" || !artifacts) return false;
  if (
    !status.run_id ||
    rawEvents.some((event) => event.run_id !== status.run_id) ||
    artifacts.report?.run_id !== status.run_id ||
    artifacts.memory?.run_id !== status.run_id ||
    artifacts.report?.final_status !== "RESOLVED" ||
    artifacts.memory?.final_status !== "RESOLVED"
  ) return false;
  const terminal = sealedTerminalEvent(rawEvents, status);
  if (
    !terminal ||
    terminal.event_type !== "run.completed" ||
    terminal.payload.verified_recovery !== true
  ) return false;
  const verifications = rawEvents.filter(
    (event) => event.event_type === "verification.result",
  );
  const latestVerification = verifications.at(-1);
  const reportOutcome = artifacts.report?.outcome;
  const memoryResolution = artifacts.memory?.resolution;
  return Boolean(
    latestVerification?.payload?.status === "passed" &&
      terminal.sequence > latestVerification.sequence &&
      status.report_available === true &&
      status.memory_available === true &&
      reportOutcome?.verification_status === "passed" &&
      reportOutcome.verification_event_id === latestVerification.event_id &&
      memoryResolution?.verification_status === "passed" &&
      memoryResolution?.verification_event_id === latestVerification.event_id,
  );
}

export function liveDisplayStatus({ status, events, artifacts, streamEnded, contractError }) {
  if (contractError) return "CONTRACT_ERROR";
  const backend = status?.status ?? "IDLE";
  if (backend === "RESOLVED" && !hasVerifiedRecovery(status, events, artifacts)) {
    return streamEnded ? "CONTRACT_ERROR" : "RUNNING";
  }
  return backend;
}

export function reportView(report) {
  return {
    title: report.title,
    finalStatus: report.final_status,
    affectedService: report.affected_service,
    evidenceCount: report.evidence_event_ids.length,
    verificationEventId: report.outcome.verification_event_id,
    summary: report.outcome.summary,
    rootCauses: report.confirmed_root_causes.map((root) => ({
      code: root.code,
      source: root.source,
      eventId: root.event_id,
    })),
    actions: report.actions.map((action) => ({
      action: action.action,
      target: action.target,
      outcome: action.outcome,
    })),
    prevention: [...report.prevention_follow_up],
  };
}

export function memoryView(memory) {
  return {
    title: memory.title,
    finalStatus: memory.final_status,
    lookupTokens: [...memory.lookup_tokens],
    normalizedEvidence: memory.normalized_evidence.map((item) => ({
      kind: item.kind,
      code: item.code,
      source: item.source,
      eventId: item.event_id,
    })),
    resolution: memory.resolution.summary,
  };
}
