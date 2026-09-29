import {
  approvalFieldEntries,
  formatApprovalValue,
  formatTimestamp,
  getApprovalPresentation,
  getResponseStatePresentation,
} from "./view-model.js";

const approvalFieldLabels = {
  action: "动作",
  target: "目标",
  scope: "范围",
  arguments: "参数",
  risk: "风险",
  expiry: "到期时间",
};

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderBadge(label, tone = "neutral") {
  return (
    '<span class="badge badge--' +
    escapeHtml(tone) +
    '">' +
    escapeHtml(label) +
    "</span>"
  );
}

function renderFactRows(facts = []) {
  return facts
    .map(
      (fact) =>
        '<div class="fact-row"><span>' +
        escapeHtml(fact.label) +
        '</span><strong title="' +
        escapeHtml(fact.value) +
        '">' +
        escapeHtml(fact.value) +
        "</strong></div>",
    )
    .join("");
}

function verificationLabel(verification) {
  if (!verification) return "";
  return verification.status === "passed" ? "验证通过" : "验证未通过";
}

export function renderStoryStrip(phases, activeIndex) {
  return phases
    .map((phase, index) => {
      const isReached = phase.eventIndex <= activeIndex;
      const isCurrent =
        phase.eventIndex <= activeIndex &&
        (phases[index + 1]?.eventIndex ?? Number.POSITIVE_INFINITY) > activeIndex;
      return (
        '<button class="story-step tone-' +
        escapeHtml(phase.tone) +
        (isReached ? " is-reached" : "") +
        (isCurrent ? " is-current" : "") +
        '" type="button" data-jump-index="' +
        phase.eventIndex +
        '" aria-current="' +
        (isCurrent ? "step" : "false") +
        '"><span class="story-step__index">' +
        String(index + 1).padStart(2, "0") +
        '</span><span class="story-step__label">' +
        escapeHtml(phase.label) +
        "</span></button>"
      );
    })
    .join("");
}

export function renderTimelineEvent(event, index, isActive) {
  const verification = event.verification
    ? renderBadge(
        verificationLabel(event.verification),
        event.verification.status === "passed" ? "success" : "danger",
      )
    : "";
  const newEvidence = event.newEvidence
    ? '<span class="event-signal">新证据 · ' +
      escapeHtml(event.newEvidence.code) +
      "</span>"
    : "";
  const action = event.action
    ? '<span class="event-action"><span>受控动作</span><code>' +
      escapeHtml(event.action.name) +
      '</code><span class="event-action__target">→ ' +
      escapeHtml(event.action.target) +
      "</span></span>"
    : "";
  return (
    '<li class="timeline-item tone-' +
    escapeHtml(event.tone) +
    (isActive ? " is-active" : "") +
    '"><span class="timeline-item__number" aria-hidden="true">' +
    String(index + 1).padStart(2, "0") +
    '</span><span class="timeline-item__line" aria-hidden="true"></span>' +
    '<span class="timeline-item__node" aria-hidden="true"><span></span></span>' +
    '<button class="event-card" type="button" data-event-index="' +
    index +
    '" aria-pressed="' +
    (isActive ? "true" : "false") +
    '"><span class="event-card__meta"><span>第 ' +
    String(index + 1).padStart(2, "0") +
    " 章 · " +
    escapeHtml(event.kicker) +
    "</span><time>" +
    escapeHtml(formatTimestamp(event.occurredAt)) +
    "</time></span>" +
    '<span class="event-card__title">' +
    escapeHtml(event.title) +
    "</span>" +
    '<span class="event-card__body"><span class="event-card__label">发生了什么</span><span class="event-card__summary">' +
    escapeHtml(event.summary) +
    "</span></span>" +
    action +
    '<span class="event-card__footer">' +
    verification +
    newEvidence +
    '<code class="event-id">' +
    escapeHtml(event.eventId) +
    "</code></span></button></li>"
  );
}

export function renderIncidentPanel(fixture, proof, responseState) {
  const incident = fixture.incident;
  const statusTone = proof.verified ? "success" : "danger";
  const durationSeconds = Math.round(
    (new Date(incident.completedAt) - new Date(incident.startedAt)) / 1000,
  );
  const rootCauses = fixture.report.rootCauses;
  const rootCauseSummary = rootCauses
    .map((root) => root.code)
    .join(" 与 ");
  const rootCauseRows = rootCauses
    .map(
      (root, index) =>
        '<div class="cause-chip' +
        (index > 0 ? " cause-chip--amber" : "") +
        '"><i></i><span><strong>' +
        escapeHtml(root.code) +
        '</strong><small>' +
        escapeHtml(root.eventId) +
        " · " +
        escapeHtml(root.source) +
        "</small></span></div>",
    )
    .join("");
  return (
    '<section class="incident-summary">' +
    '<div class="incident-summary__meta"><span class="section-kicker">已录制事故解释</span><code>' +
    escapeHtml(incident.id) +
    "</code></div>" +
    '<div class="incident-summary__heading"><h1>' +
    escapeHtml(incident.title) +
    "</h1>" +
    renderBadge(proof.status, statusTone) +
    "</div>" +
    '<p class="incident-summary__symptom">' +
    escapeHtml(incident.symptom) +
    "</p>" +
    '<div class="incident-summary__answer"><span>已确认原因</span><p><strong>' +
    escapeHtml(rootCauseSummary) +
    "</strong> 共同阻断了订单同步。Agent 根据新证据改变计划，最终由权威验证确认恢复。</p></div>" +
    '<div class="hero-proof"><div><span>恢复证明</span><strong>' +
    escapeHtml(proof.verificationEventId ?? "等待权威验证") +
    '</strong><p>动作返回成功不能建立结论；只有权威 verification.result=passed 才能显示恢复。</p></div><button type="button" class="hero-cta" data-jump-index="0">阅读完整恢复过程 <span aria-hidden="true">↓</span></button></div>' +
    '<div class="incident-summary__facts"><div><span>受影响服务</span><strong>' +
    escapeHtml(incident.affectedService) +
    '</strong></div><div><span>恢复耗时</span><strong>' +
    durationSeconds +
    ' 秒</strong></div><div><span>关联证据</span><strong>' +
    fixture.report.evidenceCount +
    ' 项</strong></div><div><span>受控动作</span><strong>' +
    fixture.report.actions.length +
    ' 次</strong></div></div>' +
    '<details class="incident-summary__extras"><summary>查看状态预览与技术根因 <span aria-hidden="true">＋</span></summary><div class="incident-summary__extras-grid">' +
    '<label class="state-picker" for="response-state"><span class="section-kicker">响应状态预览</span>' +
    '<span class="select-wrap"><select id="response-state" aria-label="切换响应状态预览">' +
    [
      ["resolved", "恢复已验证"],
      ["loading", "加载中"],
      ["error", "读取错误"],
      ["safe-stop", "安全停止"],
      ["cancelled", "已取消"],
      ["failed", "运行失败"],
    ]
      .map(
        ([value, label]) =>
          '<option value="' +
          value +
          '"' +
          (value === responseState ? " selected" : "") +
          ">" +
          label +
          "</option>",
      )
      .join("") +
    '</select><span aria-hidden="true">⌄</span></span></label>' +
    '<div class="root-cause-block"><span class="section-kicker">确认根因</span>' +
    rootCauseRows +
    "</div></div></details>" +
    "</section>"
  );
}

export function renderResponseStateBanner(state) {
  const presentation = getResponseStatePresentation(state);
  return (
    '<section class="state-banner tone-' +
    escapeHtml(presentation.tone) +
    '" aria-live="polite"><div class="state-banner__icon" aria-hidden="true"><span></span></div>' +
    '<div><span class="state-banner__label">' +
    escapeHtml(presentation.label) +
    "</span><strong>" +
    escapeHtml(presentation.title) +
    "</strong><p>" +
    escapeHtml(presentation.detail) +
    "</p></div>" +
    '<button type="button" class="text-button" data-state-action="' +
    escapeHtml(state) +
    '">' +
    escapeHtml(presentation.action) +
    " <span aria-hidden='true'>→</span></button></section>"
  );
}

export function renderEvidencePanel(event) {
  const actionSection = event.action
    ? '<section class="detail-section"><div class="detail-section__head"><span>动作边界</span>' +
      renderBadge(event.action.policyDecision, "success") +
      '</div><div class="binding-card">' +
      renderFactRows([
        { label: "action", value: event.action.name },
        { label: "target", value: event.action.target },
        { label: "risk", value: event.action.risk },
        { label: "outcome", value: event.action.outcome },
      ]) +
      "</div></section>"
    : "";
  const verificationSection = event.verification
    ? '<section class="detail-section"><div class="detail-section__head"><span>权威验证</span>' +
      renderBadge(
        event.verification.status.toUpperCase(),
        event.verification.status === "passed" ? "success" : "danger",
      ) +
      '</div><div class="verification-card tone-' +
      (event.verification.status === "passed" ? "success" : "danger") +
      '"><span class="verification-card__mark" aria-hidden="true"></span><div><strong>' +
      escapeHtml(event.verification.eventId) +
      '</strong><p>' +
      escapeHtml(event.verification.detail) +
      '</p><small>authoritative=true</small></div></div></section>'
    : "";
  const evidence = event.evidenceIds
    .map((eventId) => '<code>' + escapeHtml(eventId) + "</code>")
    .join("");
  return (
    '<div class="detail-scroll"><header class="detail-hero tone-' +
    escapeHtml(event.tone) +
    '"><div><span class="section-kicker">证据详情</span><h2>' +
    escapeHtml(event.title) +
    '</h2></div><span class="sequence">#' +
    String(event.sequence).padStart(3, "0") +
    "</span></header>" +
    '<p class="detail-summary">' +
    escapeHtml(event.summary) +
    "</p>" +
    '<section class="detail-section"><div class="detail-section__head"><span>现场事实</span><small>' +
    escapeHtml(event.eventType) +
    '</small></div><div class="binding-card">' +
    renderFactRows(event.facts) +
    "</div></section>" +
    actionSection +
    verificationSection +
    '<section class="detail-section"><div class="detail-section__head"><span>证据链</span><small>' +
    event.evidenceIds.length +
    ' 个引用</small></div><div class="evidence-links">' +
    evidence +
    "</div></section></div>"
  );
}

export function renderApprovalPanel(preview, state) {
  const presentation = getApprovalPresentation(state);
  const fields = approvalFieldEntries(preview)
    .map(
      ({ key, value }) =>
        '<div class="approval-field"><span>' +
        escapeHtml(approvalFieldLabels[key] ?? key) +
        '</span><strong data-approval-field="' +
        escapeHtml(key) +
        '">' +
        escapeHtml(formatApprovalValue(value)) +
        "</strong></div>",
    )
    .join("");
  const stateButtons = ["pending", "approved", "denied", "expired"]
    .map((item) => {
      const label = {
        pending: "待批准",
        approved: "已批准",
        denied: "已拒绝",
        expired: "已过期",
      }[item];
      return (
        '<button type="button" data-approval-state="' +
        item +
        '" class="' +
        (item === state ? "is-active" : "") +
        '" aria-pressed="' +
        (item === state ? "true" : "false") +
        '">' +
        label +
        "</button>"
      );
    })
    .join("");
  const actions =
    state === "pending"
      ? '<div class="approval-actions"><button type="button" class="button button--primary" data-approval-transition="approved">批准这一项</button><button type="button" class="button button--quiet" data-approval-transition="denied">拒绝并停止</button></div>'
      : '<button type="button" class="button button--quiet button--full" data-approval-state="pending">回到待批准预览</button>';
  return (
    '<div class="detail-scroll"><header class="detail-hero tone-' +
    escapeHtml(presentation.tone) +
    '"><div><span class="section-kicker">审批边界 · 仅预览</span><h2>' +
    escapeHtml(presentation.title) +
    '</h2></div><span class="shield-mark" aria-hidden="true">◇</span></header>' +
    '<p class="detail-summary">' +
    escapeHtml(presentation.detail) +
    '</p><div class="state-segments" aria-label="审批状态预览">' +
    stateButtons +
    '</div><section class="approval-card tone-' +
    escapeHtml(presentation.tone) +
    '"><div class="approval-card__top"><div>' +
    renderBadge(presentation.label, presentation.tone) +
    '<code>' +
    escapeHtml(preview.requestId) +
    '</code></div><span>exact binding</span></div><div class="approval-fields">' +
    fields +
    '</div><div class="approval-guard"><span class="guard-dot"></span><p><strong>单次 · 短期 · 不可扩权</strong><br>批准只生成 grant；后续仍需 ExecutionGuard，且批准不等于执行。</p></div>' +
    actions +
    '</section><aside class="preview-note"><strong>' +
    escapeHtml(preview.sourceLabel) +
    '</strong><p>' +
    escapeHtml(preview.disclaimer) +
    "</p></aside></div>"
  );
}

export function renderReportPanel(report, { verifiedRecovery = false } = {}) {
  const recovered = verifiedRecovery && report.finalStatus === "RESOLVED";
  const roots = report.rootCauses
    .map(
      (root, index) =>
        '<div class="cause-line"><span>' +
        String(index + 1).padStart(2, "0") +
        '</span><div><strong>' +
        escapeHtml(root.code) +
        '</strong><small>' +
        escapeHtml(root.source) +
        " · " +
        escapeHtml(root.eventId) +
        "</small></div></div>",
    )
    .join("");
  const actions = report.actions
    .map(
      (action) =>
        '<tr><td><code>' +
        escapeHtml(action.action) +
        '</code><small>' +
        escapeHtml(action.target) +
        '</small></td><td>' +
        renderBadge(
          action.outcome,
          action.outcome === "failed" ? "danger" : recovered ? "success" : "neutral",
        ) +
        "</td></tr>",
    )
    .join("");
  const prevention = report.prevention
    .map(
      (item, index) =>
        '<li><span>' +
        String(index + 1) +
        "</span><p>" +
        escapeHtml(item) +
        "</p></li>",
    )
    .join("");
  return (
    '<div class="detail-scroll"><header class="detail-hero tone-' +
    (recovered ? "success" : "danger") +
    '"><div><span class="section-kicker">事故报告</span><h2>' +
    escapeHtml(report.title) +
    '</h2></div>' +
    renderBadge(report.finalStatus, recovered ? "success" : "danger") +
    '</header><p class="detail-summary">' +
    escapeHtml(
      recovered
        ? report.summary
        : "本次运行未建立可验证恢复结论。下一步：检查最后证据并处理阻塞项。",
    ) +
    '</p><div class="artifact-proof"><div><span>' +
    (recovered ? "恢复证明" : "恢复未完成") +
    '</span><strong>' +
    escapeHtml(recovered ? report.verificationEventId : report.finalStatus) +
    '</strong></div><div><span>关联证据</span><strong>' +
    report.evidenceCount +
    '</strong></div></div><section class="detail-section"><div class="detail-section__head"><span>确认根因</span><small>2 项</small></div><div class="cause-lines">' +
    roots +
    '</div></section><section class="detail-section"><div class="detail-section__head"><span>动作结果</span><small>按发生顺序</small></div><table class="action-table"><tbody>' +
    actions +
    '</tbody></table></section><section class="detail-section"><div class="detail-section__head"><span>预防跟进</span><small>report</small></div><ol class="prevention-list">' +
    prevention +
    "</ol></section></div>"
  );
}

export function renderMemoryPanel(memory, { verifiedRecovery = false } = {}) {
  const recovered = verifiedRecovery && memory.finalStatus === "RESOLVED";
  const tokens = memory.lookupTokens
    .map((token) => '<code>' + escapeHtml(token) + "</code>")
    .join("");
  const evidence = memory.normalizedEvidence
    .map(
      (item) =>
        '<div class="memory-evidence"><span class="memory-evidence__kind">' +
        escapeHtml(item.kind.replace("_", " ")) +
        '</span><div><strong>' +
        escapeHtml(item.code) +
        '</strong><small>' +
        escapeHtml(item.source) +
        " · " +
        escapeHtml(item.eventId) +
        "</small></div></div>",
    )
    .join("");
  return (
    '<div class="detail-scroll"><header class="detail-hero tone-' +
    (recovered ? "plan" : "danger") +
    '"><div><span class="section-kicker">事故记忆</span><h2>下次可直接检索的经验</h2></div>' +
    renderBadge(memory.finalStatus, recovered ? "success" : "danger") +
    '</header><p class="detail-summary">' +
    (recovered
      ? "保留症状、根因、动作链和证据引用；不保存密钥、原始提示或生产数据。"
      : "本次记录不代表事故已恢复。下一步：检查最后证据并完成权威验证。") +
    '<section class="detail-section"><div class="detail-section__head"><span>检索词</span><small>' +
    memory.lookupTokens.length +
    ' 个</small></div><div class="token-cloud">' +
    tokens +
    '</div></section><section class="detail-section"><div class="detail-section__head"><span>规范化证据</span><small>memory</small></div><div class="memory-evidence-list">' +
    evidence +
    '</div></section><section class="resolution-chain"><span>' +
    (recovered ? "已验证恢复链" : "恢复未完成") +
    '</span><p>' +
    escapeHtml(
      recovered
        ? memory.resolution
        : "下一步：修复阻塞项，并用封口终态后的权威证据重新验证。",
    ) +
    "</p></section></div>"
  );
}

export function renderProvenance(fixture) {
  return (
    '<div class="provenance-card"><span class="provenance-card__pulse" aria-hidden="true"></span><div><strong>' +
    escapeHtml(fixture.provenance.label) +
    '</strong><p>Fixture playback · 不连接后端 · 不执行操作</p></div><code>' +
    escapeHtml(fixture.provenance.runId) +
    "</code></div>"
  );
}
