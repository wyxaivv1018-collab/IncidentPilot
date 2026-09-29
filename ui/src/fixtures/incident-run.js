const freeze = (value) => {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    Object.values(value).forEach(freeze);
  }
  return value;
};

export const incidentRunFixture = freeze({
  provenance: {
    mode: "recorded-redacted-fixture",
    label: "已录制 · 脱敏合成运行",
    runId: "RUN-C06CR-2a56c726b208",
    sourceTrace:
      "artifacts/acceptance/agent-run-c06-contract-reset-golden-attempt-2.json",
    sourceReport:
      "runtime/c07-acceptance/RUN-C06CR-2a56c726b208/incident-report.json",
    sourceMemory:
      "runtime/c07-acceptance/RUN-C06CR-2a56c726b208/incident-memory.json",
    apiContract: "docs/api/contract.md",
    schemaVersion: "1.1",
    provider: "deepseek-v4-flash",
  },
  incident: {
    id: "INC-ORDER-SYNC-001",
    scenarioId: "order-sync-double-fault",
    title: "订单同步失败",
    affectedService: "order-sync",
    symptom: "订单同步请求超时，作业保持失败状态。",
    startedAt: "2026-08-28T12:14:24.963698+00:00",
    completedAt: "2026-08-28T12:14:42+00:00",
    terminalStatus: "RESOLVED",
  },
  timeline: [
    {
      eventId: "EVT-000009",
      sequence: 9,
      occurredAt: "2026-08-28T12:14:25+00:00",
      eventType: "tool.result",
      phase: "investigate",
      tone: "info",
      kicker: "调查",
      title: "先读取现状，不猜原因",
      summary:
        "日志显示 SYNC_TIMEOUT；环境证据显示 sync-worker 已停止，数据库仍健康。",
      evidenceIds: ["EVT-000007", "EVT-000009"],
      facts: [
        { label: "可见症状", value: "SYNC_TIMEOUT" },
        { label: "首个根因", value: "worker_status:stopped" },
        { label: "数据库", value: "healthy" },
      ],
    },
    {
      eventId: "EVT-000013",
      sequence: 13,
      occurredAt: "2026-08-28T12:14:31+00:00",
      eventType: "agent.summary",
      phase: "plan",
      tone: "plan",
      kicker: "初始计划",
      title: "先恢复 worker，再重试同步",
      summary:
        "计划由模型给出，并明确链接 EVT-000007 与 EVT-000009：重启停止的 worker，重试订单同步，随后做权威验证。",
      evidenceIds: ["EVT-000007", "EVT-000009", "EVT-000013"],
      facts: [
        { label: "决策来源", value: "provider-originated plan" },
        { label: "下一步", value: "restart → retry → verify" },
      ],
    },
    {
      eventId: "EVT-000021",
      sequence: 21,
      occurredAt: "2026-08-28T12:14:32+00:00",
      eventType: "verification.result",
      phase: "first-repair",
      tone: "warning",
      kicker: "修复 1 · 未恢复",
      title: "worker 已运行，但事故仍未解决",
      summary:
        "ExecutionGuard 允许低风险重启；操作成功不等于事故恢复。同步验证仍为 failed。",
      evidenceIds: [
        "EVT-000017",
        "EVT-000018",
        "EVT-000019",
        "EVT-000021",
      ],
      action: {
        name: "restart_noncritical_worker",
        target: "sync-worker",
        risk: "LOW",
        policyDecision: "ALLOW",
        outcome: "succeeded",
      },
      verification: {
        eventId: "EVT-000021",
        status: "failed",
        authoritative: true,
        detail: "订单同步仍保持失败。",
      },
      facts: [
        { label: "worker", value: "running" },
        { label: "sync job", value: "failed" },
      ],
    },
    {
      eventId: "EVT-000030",
      sequence: 30,
      occurredAt: "2026-08-28T12:14:33+00:00",
      eventType: "verification.result",
      phase: "failed-repair",
      tone: "danger",
      kicker: "修复 2 · 暴露新证据",
      title: "重试失败，发现 CACHE_LOCK",
      summary:
        "重试动作返回 failed，并暴露此前不可见的缓存锁。同步屏障再次给出权威 failed。",
      evidenceIds: [
        "EVT-000026",
        "EVT-000027",
        "EVT-000028",
        "EVT-000030",
        "EVT-000032",
      ],
      action: {
        name: "retry_sync_job",
        target: "order-sync-job-001",
        risk: "LOW",
        policyDecision: "ALLOW",
        outcome: "failed",
      },
      verification: {
        eventId: "EVT-000030",
        status: "failed",
        authoritative: true,
        detail: "CACHE_LOCK 仍在，订单同步仍失败。",
      },
      newEvidence: {
        code: "CACHE_LOCK",
        findingId: "LOG-ORDER-SYNC-002",
        source: "order-sync-cache",
      },
      facts: [
        { label: "新发现", value: "CACHE_LOCK" },
        { label: "来源", value: "order-sync-cache" },
      ],
    },
    {
      eventId: "EVT-000036",
      sequence: 36,
      occurredAt: "2026-08-28T12:14:35+00:00",
      eventType: "agent.summary",
      phase: "replan",
      tone: "replan",
      kicker: "基于证据重规划",
      title: "先清除缓存锁，再重试",
      summary:
        "模型引用 EVT-000032 更新计划：worker 已运行，阻塞点改为缓存锁；清理有界缓存后再重试并验证。",
      evidenceIds: ["EVT-000032", "EVT-000036"],
      facts: [
        { label: "计划变化", value: "restart → clear cache" },
        { label: "证据链接", value: "EVT-000032 / CACHE_LOCK" },
      ],
    },
    {
      eventId: "EVT-000044",
      sequence: 44,
      occurredAt: "2026-08-28T12:14:37+00:00",
      eventType: "verification.result",
      phase: "recovery",
      tone: "warning",
      kicker: "修复 3 · 尚未恢复",
      title: "缓存锁已清除，仍等待最终重试",
      summary:
        "有界缓存清理成功；同步作业尚未重试，所以权威验证仍为 failed，界面不提前显示恢复。",
      evidenceIds: [
        "EVT-000040",
        "EVT-000041",
        "EVT-000042",
        "EVT-000044",
      ],
      action: {
        name: "clear_application_cache",
        target: "order-sync",
        arguments: { max_keys: 100 },
        risk: "LOW",
        policyDecision: "ALLOW",
        outcome: "succeeded",
      },
      verification: {
        eventId: "EVT-000044",
        status: "failed",
        authoritative: true,
        detail: "cache_lock=cleared；sync_job_status=failed。",
      },
      facts: [
        { label: "cache lock", value: "cleared" },
        { label: "sync job", value: "failed" },
      ],
    },
    {
      eventId: "EVT-000053",
      sequence: 53,
      occurredAt: "2026-08-28T12:14:38+00:00",
      eventType: "verification.result",
      phase: "verified",
      tone: "success",
      kicker: "权威恢复证明",
      title: "重试成功，验证通过",
      summary:
        "最后一次重试成功；只有 EVT-000053 的权威 passed 结果把运行状态推进到 RESOLVED。",
      evidenceIds: [
        "EVT-000049",
        "EVT-000050",
        "EVT-000051",
        "EVT-000053",
      ],
      action: {
        name: "retry_sync_job",
        target: "order-sync-job-001",
        risk: "LOW",
        policyDecision: "ALLOW",
        outcome: "succeeded",
      },
      verification: {
        eventId: "EVT-000053",
        status: "passed",
        authoritative: true,
        detail: "sync_job_status=success；incident_resolved=true。",
      },
      facts: [
        { label: "sync job", value: "success" },
        { label: "incident", value: "resolved" },
      ],
    },
    {
      eventId: "EVT-000063",
      sequence: 63,
      occurredAt: "2026-08-28T12:14:42+00:00",
      eventType: "run.completed",
      phase: "published",
      tone: "success",
      kicker: "结果沉淀",
      title: "报告与事故记忆已就绪",
      summary:
        "运行以 verified_recovery=true 结束；C07 使用同一轨迹生成严格校验的报告和可检索记忆。",
      evidenceIds: ["EVT-000053", "EVT-000059", "EVT-000063"],
      terminal: {
        status: "RESOLVED",
        verifiedRecovery: true,
      },
      artifacts: ["incident-report.json", "incident-memory.json"],
      facts: [
        { label: "报告证据", value: "22 linked events" },
        { label: "运行结论", value: "RESOLVED" },
      ],
    },
  ],
  approvalPreview: {
    sourceLabel: "C08 exact-action contract example",
    disclaimer: "状态预览；不属于这次 Golden 低风险运行，也不会发送请求。",
    requestId: "APR-PREVIEW-001",
    canonical: {
      action: "restart_database",
      target: "orders-primary",
      scope: ["orders-primary"],
      arguments: { strategy: "rolling" },
      risk: "HIGH",
      expiry: "2026-09-01T00:05:00+00:00",
    },
    singleUse: true,
  },
  report: {
    title: "Order synchronization failed",
    finalStatus: "RESOLVED",
    affectedService: "order-sync",
    evidenceCount: 22,
    verificationEventId: "EVT-000053",
    summary:
      "sync-worker 停止与 CACHE_LOCK 共同导致 SYNC_TIMEOUT。恢复链为：重启 worker、清除有界缓存、重试同步；最终由权威验证确认恢复。",
    rootCauses: [
      {
        code: "worker_status:stopped",
        source: "environment",
        eventId: "EVT-000009",
      },
      {
        code: "CACHE_LOCK",
        source: "order-sync-cache",
        eventId: "EVT-000032",
      },
    ],
    actions: [
      {
        action: "restart_noncritical_worker",
        target: "sync-worker",
        outcome: "succeeded",
      },
      {
        action: "retry_sync_job",
        target: "order-sync-job-001",
        outcome: "failed",
      },
      {
        action: "clear_application_cache",
        target: "order-sync",
        outcome: "succeeded",
      },
      {
        action: "retry_sync_job",
        target: "order-sync-job-001",
        outcome: "succeeded",
      },
    ],
    prevention: [
      "监控 worker_status:stopped 的复发，并关联 EVT-000009。",
      "监控 CACHE_LOCK 的复发，并关联 EVT-000032。",
      "任何恢复结论都必须等待权威验证。",
    ],
  },
  memory: {
    title: "Order synchronization failed",
    finalStatus: "RESOLVED",
    lookupTokens: [
      "cache_lock",
      "order-sync",
      "sync_timeout",
      "worker_status:stopped",
      "clear_application_cache",
    ],
    normalizedEvidence: [
      {
        kind: "symptom",
        code: "SYNC_TIMEOUT",
        source: "order-sync",
        eventId: "EVT-000007",
      },
      {
        kind: "root_cause",
        code: "worker_status:stopped",
        source: "environment",
        eventId: "EVT-000009",
      },
      {
        kind: "root_cause",
        code: "CACHE_LOCK",
        source: "order-sync-cache",
        eventId: "EVT-000032",
      },
    ],
    resolution:
      "restart_noncritical_worker → clear_application_cache → retry_sync_job → authoritative verification passed",
  },
  externalStatus: {
    bedrock: "BLOCKED / MUST RESOLVE",
    note: "Bedrock 是独立未解决问题；本次 DeepSeek 合成运行不关闭它。",
  },
});

export const responseStateOrder = freeze([
  "resolved",
  "loading",
  "error",
  "safe-stop",
  "cancelled",
  "failed",
]);

export const approvalStateOrder = freeze([
  "pending",
  "approved",
  "denied",
  "expired",
]);

