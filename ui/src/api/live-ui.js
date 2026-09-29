import { escapeHtml } from "../lib/components.js";

function badge(label, tone = "neutral") {
  return (
    '<span class="badge badge--' +
    escapeHtml(tone) +
    '">' +
    escapeHtml(label) +
    "</span>"
  );
}

function formatValue(value) {
  if (Array.isArray(value)) return value.join(" · ");
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => key + "=" + item)
      .join(" · ");
  }
  return String(value ?? "—");
}

export function renderLiveIncident({ status, timeline, verified, report, displayStatus }) {
  const runStatus = status?.status ?? "IDLE";
  const visibleStatus = displayStatus ?? (runStatus === "RESOLVED" && !verified ? "RUNNING" : runStatus);
  const finalizing = runStatus === "RESOLVED" && !verified && visibleStatus !== "CONTRACT_ERROR";
  const runId = status?.run_id ?? "尚未启动";
  const passed = timeline
    .filter(
      (event) =>
        event.verification?.status === "passed" &&
        event.verification?.authoritative === true &&
        typeof event.verification?.eventId === "string" &&
        event.verification.eventId.length > 0,
    )
    .at(-1);
  const actionCount = timeline.filter((event) => event.action).length;
  const roots = report?.rootCauses ?? [];
  const rootText = roots.length
    ? roots.map((root) => root.code).join(" 与 ")
    : "等待实时证据确认";
  const active = ["STARTING", "RUNNING", "CANCEL_REQUESTED"].includes(runStatus);
  const action = finalizing ? "wait" : active ? "cancel" : "start";
  const actionLabel = finalizing ? "正在核验结果" : active ? "取消当前运行" : runStatus === "IDLE" ? "启动真实演示" : "启动新运行";
  return (
    '<section class="incident-summary"><div class="incident-summary__meta"><span class="section-kicker">实时本地运行 · C08 API / SSE</span><code>' +
    escapeHtml(runId) +
    '</code></div><div class="incident-summary__heading"><h1>订单同步失败</h1>' +
    badge(verified ? "RESOLVED" : visibleStatus, verified ? "success" : "neutral") +
    '</div><p class="incident-summary__symptom">真实 Agent 运行的事件会按后端序号进入这条证据链；页面不会从历史 fixture 推断结果。</p>' +
    '<div class="incident-summary__answer"><span>当前结论</span><p><strong>' +
    escapeHtml(rootText) +
    "</strong>。只有同一 live run 的最终权威验证、Report 与 Memory 都通过后，界面才显示恢复。</p></div>" +
    '<div class="hero-proof"><div><span>' +
    (verified ? "恢复证明" : "恢复未完成") +
    '</span><strong>' +
    escapeHtml(
      verified
        ? passed?.verification?.eventId ?? "缺少权威 verification.result"
        : "尚未建立权威恢复闭环",
    ) +
    '</strong><p>' +
    (verified
      ? "动作成功、批准成功或模型文本都不能单独建立 RESOLVED。"
      : "下一步：检查最后一条证据，修复阻塞后再启动新运行。") +
    '</p></div><button type="button" class="hero-cta" data-live-action="' +
    action +
    '"' + (finalizing ? " disabled" : "") + '>' +
    escapeHtml(actionLabel) +
    ' <span aria-hidden="true">→</span></button></div>' +
    '<div class="incident-summary__facts"><div><span>受影响服务</span><strong>order-sync</strong></div><div><span>后端状态</span><strong>' +
    escapeHtml(finalizing ? "等待制品校验" : visibleStatus) +
    '</strong></div><div><span>已收事件</span><strong>' +
    String(status?.event_count ?? 0) +
    '</strong></div><div><span>受控动作</span><strong>' +
    String(actionCount) +
    " 次</strong></div></div></section>"
  );
}

const statusCopy = {
  IDLE: ["准备就绪", "等待启动真实本地运行", "点击“启动真实演示”；系统会连接同源 C08 API 和 SSE。", "start", "启动运行", "info"],
  STARTING: ["正在启动", "本地运行已接受", "正在建立实时证据流；此时尚无恢复结论。", "cancel", "取消运行", "info"],
  RUNNING: ["实时运行中", "Agent 正在依据证据行动", "保持页面打开；新事件会严格按后端序号追加。", "cancel", "取消运行", "info"],
  CANCEL_REQUESTED: ["正在取消", "等待受控运行停止", "活动槽位会保持到 worker 有界停止，未使用授权将撤销。", "wait", "等待停止", "warning"],
  CANCELLED: ["已取消", "运行已安全停止", "未显示恢复；可以检查最后证据，或启动一条新运行。", "start", "启动新运行", "neutral"],
  RESOLVED: ["恢复已验证", "权威证据和制品已闭环", "Report 与 Memory 均来自当前 live run。", "report", "查看事故报告", "success"],
  UNRESOLVED: ["仍未恢复", "运行正常结束但事故未闭环", "查看最后一条证据后再启动新运行。", "evidence", "查看最后证据", "warning"],
  FAILED: ["运行失败", "没有建立恢复结论", "保留现有证据；检查最后事件后再诊断。", "evidence", "查看最后证据", "danger"],
  TIMEOUT: ["运行超时", "有界时间已用尽", "没有显示恢复；检查最后证据再决定是否重试。", "evidence", "查看最后证据", "danger"],
  BUDGET_EXCEEDED: ["预算已到", "运行按预算边界停止", "没有显示恢复；检查模型轮次和工具证据。", "evidence", "查看最后证据", "warning"],
  AUTH_BLOCKED: ["需要外部凭据", "DeepSeek 认证前置条件缺失", "在启动命令所在 PowerShell 配置 DEEPSEEK_API_KEY 后，重新运行本地启动脚本。", "start", "条件就绪后重试", "warning"],
  RUNTIME_BLOCKED: ["运行时缺失", "受审 Strands OpenAI provider 不可用", "使用 scripts/run_full_demo.ps1 启动；它只在凭据存在时加载固定 Strands 版本。", "start", "修复后重试", "warning"],
  CONTRACT_ERROR: ["证据被拒绝", "实时数据不符合冻结契约", "页面已 fail closed，不会据此显示恢复；请查看错误并重新启动服务。", "evidence", "查看已收证据", "danger"],
};

export function renderLiveStatus(statusName, detail = "") {
  const [label, title, copy, action, actionLabel, tone] =
    statusCopy[statusName] ?? statusCopy.CONTRACT_ERROR;
  const displayedDetail = detail || copy;
  return (
    '<section class="state-banner tone-' +
    tone +
    '" aria-live="polite"><div class="state-banner__icon" aria-hidden="true"><span></span></div><div><span class="state-banner__label">' +
    escapeHtml(label) +
    "</span><strong>" +
    escapeHtml(title) +
    "</strong><p>" +
    escapeHtml(displayedDetail) +
    '</p></div><button type="button" class="text-button" data-live-action="' +
    action +
    '">' +
    escapeHtml(actionLabel) +
    ' <span aria-hidden="true">→</span></button></section>'
  );
}

export function renderLiveApproval(approval, message = "") {
  if (!approval) {
    return (
      '<div class="detail-scroll"><header class="detail-hero tone-neutral"><div><span class="section-kicker">实时审批边界</span><h2>当前没有待批准动作</h2></div><span class="shield-mark" aria-hidden="true">◇</span></header>' +
      '<p class="detail-summary">只有受信任运行代码注册的 HIGH 风险请求才会出现。批准不会绕过 ExecutionGuard，也不等于执行或恢复。</p>' +
      (message ? '<aside class="preview-note"><strong>最近结果</strong><p>' + escapeHtml(message) + "</p></aside>" : "") +
      "</div>"
    );
  }
  const fields = [
    ["动作", approval.action],
    ["目标", approval.target],
    ["范围", approval.scope],
    ["参数", approval.arguments],
    ["风险", approval.risk],
    ["到期时间", approval.expires_at],
  ]
    .map(
      ([label, value]) =>
        '<div class="approval-field"><span>' +
        escapeHtml(label) +
        "</span><strong>" +
        escapeHtml(formatValue(value)) +
        "</strong></div>",
    )
    .join("");
  return (
    '<div class="detail-scroll"><header class="detail-hero tone-warning"><div><span class="section-kicker">实时审批边界 · 精确绑定</span><h2>仅批准下列一次操作</h2></div><span class="shield-mark" aria-hidden="true">◇</span></header>' +
    '<p class="detail-summary">前端只回显服务端登记的 action、target、scope 和 arguments；确认时原样回传，不允许编辑或扩权。</p>' +
    '<section class="approval-card tone-warning"><div class="approval-card__top"><div>' +
    badge("等待精确批准", "warning") +
    "<code>" +
    escapeHtml(approval.approval_request_id) +
    '</code></div><span>single use</span></div><div class="approval-fields">' +
    fields +
    '</div><div class="approval-guard"><span class="guard-dot"></span><p><strong>批准 ≠ 执行 ≠ 恢复</strong><br>批准后仍必须经过 ExecutionGuard，最终恢复仍需权威验证。</p></div>' +
    '<div class="approval-actions"><button type="button" class="button button--primary" data-live-approve>批准这一精确绑定</button><button type="button" class="button button--quiet" data-live-action="cancel">拒绝并取消运行</button></div></section></div>'
  );
}

export function renderLiveEmpty(title, detail) {
  return (
    '<div class="detail-scroll"><header class="detail-hero tone-info"><div><span class="section-kicker">实时证据</span><h2>' +
    escapeHtml(title) +
    '</h2></div><span class="sequence">LIVE</span></header><p class="detail-summary">' +
    escapeHtml(detail) +
    "</p></div>"
  );
}

export function renderLiveProvenance({ runId, status, lastSequence, connected }) {
  return (
    '<div class="provenance-card"><span class="provenance-card__pulse" aria-hidden="true"></span><div><strong>实时本地运行 · C08</strong><p>Same-origin API + SSE · exact approval · ExecutionGuard</p></div><code>' +
    escapeHtml(
      (runId ?? "not-started") +
        " · " +
        status +
        " · seq=" +
        lastSequence +
        " · " +
        (connected ? "stream-connected" : "stream-idle"),
    ) +
    "</code></div>"
  );
}
