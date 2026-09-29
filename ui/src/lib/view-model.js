const canonicalApprovalFields = [
  "action",
  "target",
  "scope",
  "arguments",
  "risk",
  "expiry",
];

const statePresentations = {
  resolved: {
    label: "恢复已验证",
    title: "权威证据已闭环",
    detail: "EVT-000053=passed；报告与事故记忆可读取。",
    action: "查看恢复证据",
    tone: "success",
  },
  loading: {
    label: "正在读取",
    title: "正在装载已录制证据",
    detail: "保持当前页面；装载完成前没有可执行操作。",
    action: "等待数据就绪",
    tone: "info",
  },
  error: {
    label: "读取失败",
    title: "证据视图暂不可用",
    detail: "没有推断运行结果。检查本地预览后再重试读取。",
    action: "重新读取",
    tone: "danger",
  },
  "safe-stop": {
    label: "安全停止",
    title: "策略阻止了继续执行",
    detail: "未执行越界操作；请先查看拒绝原因和精确授权边界。",
    action: "查看拒绝原因",
    tone: "warning",
  },
  cancelled: {
    label: "已取消",
    title: "运行已停止",
    detail: "待处理与未使用授权已撤销，不会继续读取或执行动作。",
    action: "查看取消证据",
    tone: "neutral",
  },
  failed: {
    label: "运行失败",
    title: "事故没有被标记为恢复",
    detail: "终态失败且没有权威 passed 证明；保留证据后再诊断。",
    action: "查看最后证据",
    tone: "danger",
  },
};

const approvalPresentations = {
  pending: {
    label: "等待精确批准",
    title: "仅批准下列一次操作",
    detail: "必须逐字段完全匹配；批准只发放短期、单次授权，并不执行动作。",
    tone: "warning",
  },
  approved: {
    label: "已批准",
    title: "单次授权已发放",
    detail: "授权仍需经过 ExecutionGuard；批准本身不是执行，也不是恢复证明。",
    tone: "success",
  },
  denied: {
    label: "已拒绝",
    title: "没有执行动作",
    detail: "绑定不匹配或用户拒绝都会 fail closed；范围不会被扩大。",
    tone: "danger",
  },
  expired: {
    label: "已过期",
    title: "请求已关闭",
    detail: "过期授权不可确认、不可复用；需要受信任运行代码重新注册。",
    tone: "neutral",
  },
};

export function clampStep(value, eventCount) {
  if (!Number.isFinite(value) || eventCount <= 0) return 0;
  return Math.min(Math.max(Math.trunc(value), 0), eventCount - 1);
}

export function visibleTimeline(events, activeIndex) {
  const end = clampStep(activeIndex, events.length);
  return events.slice(0, end + 1);
}

export function deriveRecoveryProof(events) {
  const passed = events.find(
    (event) =>
      event.eventType === "verification.result" &&
      event.verification?.authoritative === true &&
      event.verification?.status === "passed",
  );
  const terminal = events.find(
    (event) =>
      event.eventType === "run.completed" &&
      event.terminal?.verifiedRecovery === true,
  );
  if (!passed || !terminal || passed.sequence >= terminal.sequence) {
    return {
      status: "UNRESOLVED",
      verified: false,
      verificationEventId: null,
    };
  }
  return {
    status: "RESOLVED",
    verified: true,
    verificationEventId: passed.verification.eventId,
  };
}

export function storyPhases(events) {
  const phases = [];
  for (const [index, event] of events.entries()) {
    if (!phases.some((phase) => phase.id === event.phase)) {
      phases.push({
        id: event.phase,
        label: event.kicker,
        tone: event.tone,
        eventIndex: index,
      });
    }
  }
  return phases;
}

export function approvalFieldEntries(approvalPreview) {
  return canonicalApprovalFields.map((key) => ({
    key,
    value: approvalPreview.canonical[key],
  }));
}

export function getResponseStatePresentation(state) {
  return statePresentations[state] ?? statePresentations.error;
}

export function getApprovalPresentation(state) {
  return approvalPresentations[state] ?? approvalPresentations.denied;
}

export function formatTimestamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatApprovalValue(value) {
  if (Array.isArray(value)) return value.join(" · ");
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => key + "=" + item)
      .join(" · ");
  }
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date(value));
  }
  return String(value);
}

export function validateFixtureStory(fixture) {
  const phases = new Set(fixture.timeline.map((event) => event.phase));
  const required = ["plan", "failed-repair", "replan", "verified"];
  const missing = required.filter((phase) => !phases.has(phase));
  const proof = deriveRecoveryProof(fixture.timeline);
  const replan = fixture.timeline.find((event) => event.phase === "replan");
  const failedRepair = fixture.timeline.find(
    (event) => event.phase === "failed-repair",
  );
  return {
    valid:
      missing.length === 0 &&
      proof.verified &&
      Boolean(failedRepair?.newEvidence?.code) &&
      replan?.evidenceIds?.includes("EVT-000032"),
    missing,
    proof,
  };
}

