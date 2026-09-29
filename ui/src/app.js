import {
  approvalStateOrder,
  incidentRunFixture,
  responseStateOrder,
} from "./fixtures/incident-run.js";
import {
  renderApprovalPanel,
  renderEvidencePanel,
  renderIncidentPanel,
  renderMemoryPanel,
  renderProvenance,
  renderReportPanel,
  renderResponseStateBanner,
  renderStoryStrip,
  renderTimelineEvent,
} from "./lib/components.js";
import {
  clampStep,
  deriveRecoveryProof,
  storyPhases,
  validateFixtureStory,
  visibleTimeline,
} from "./lib/view-model.js";
import { IncidentPilotApiClient } from "./api/client.js";
import {
  renderLiveApproval,
  renderLiveEmpty,
  renderLiveIncident,
  renderLiveProvenance,
  renderLiveStatus,
} from "./api/live-ui.js";
import {
  activeRunStates,
  appendLiveTraceEvent,
  assertArtifactPair,
  assertSealedTerminalTrace,
  hasVerifiedRecovery,
  liveDisplayStatus,
  liveTimeline,
  memoryView,
  reportView,
  terminalRunStates,
} from "./types/api-contract.js";

const elements = {
  incidentPanel: document.querySelector("#incident-panel"),
  storyStrip: document.querySelector("#story-strip"),
  storyProgress: document.querySelector("#story-progress"),
  timelineList: document.querySelector("#timeline-list"),
  timelineEnd: document.querySelector("#timeline-end"),
  responseBanner: document.querySelector("#response-banner"),
  detailContent: document.querySelector("#detail-content"),
  detailPanel: document.querySelector("#detail-panel"),
  provenance: document.querySelector("#provenance"),
  stepBack: document.querySelector("#step-back"),
  stepForward: document.querySelector("#step-forward"),
  autoplay: document.querySelector("#autoplay"),
  replay: document.querySelector("#replay"),
};

function renderTabs(panel) {
  document.querySelectorAll("[data-panel]").forEach((button) => {
    const selected = button.dataset.panel === panel;
    button.setAttribute("aria-selected", String(selected));
    button.classList.toggle("is-active", selected);
  });
}

function configureModeLabels({ live }) {
  const context = document.querySelector(".topbar__context span:nth-of-type(2)");
  const status = document.querySelector(".recorded-pill");
  const kicker = document.querySelector(".timeline-header .section-kicker");
  if (context) context.textContent = live ? "Live local run" : "Recorded fixture";
  if (status) status.innerHTML = live ? "<i></i>LIVE" : "<i></i>RECORDED";
  if (kicker) {
    kicker.textContent = live ? "Live incident story" : "Recorded incident story";
  }
  document.body.dataset.sourceMode = live ? "live-c08-sse" : "recorded-fixture";
}

function startRecordedMode() {
  configureModeLabels({ live: false });
  const fixture = incidentRunFixture;
  const validation = validateFixtureStory(fixture);
  if (!validation.valid) {
    throw new Error(
      "M03 fixture failed its causal-story contract: " +
        validation.missing.join(", "),
    );
  }

  const state = {
    activeIndex: fixture.timeline.length - 1,
    selectedIndex: fixture.timeline.length - 2,
    panel: "evidence",
    responseState: "resolved",
    approvalState: "pending",
    playing: false,
    timer: null,
  };
  const proof = deriveRecoveryProof(fixture.timeline);
  const phases = storyPhases(fixture.timeline);

  function renderDetail() {
    if (state.panel === "safety") {
      elements.detailContent.innerHTML = renderApprovalPanel(
        fixture.approvalPreview,
        state.approvalState,
      );
      return;
    }
    if (state.panel === "report") {
      elements.detailContent.innerHTML = renderReportPanel(fixture.report, {
        verifiedRecovery: proof.verified,
      });
      return;
    }
    if (state.panel === "memory") {
      elements.detailContent.innerHTML = renderMemoryPanel(fixture.memory, {
        verifiedRecovery: proof.verified,
      });
      return;
    }
    elements.detailContent.innerHTML = renderEvidencePanel(
      fixture.timeline[state.selectedIndex],
    );
  }

  function render() {
    state.activeIndex = clampStep(state.activeIndex, fixture.timeline.length);
    state.selectedIndex = Math.min(
      clampStep(state.selectedIndex, fixture.timeline.length),
      state.activeIndex,
    );
    const visible = visibleTimeline(fixture.timeline, state.activeIndex);
    elements.incidentPanel.innerHTML = renderIncidentPanel(
      fixture,
      proof,
      state.responseState,
    );
    elements.storyStrip.innerHTML = renderStoryStrip(phases, state.activeIndex);
    elements.storyProgress.textContent =
      String(state.activeIndex + 1).padStart(2, "0") +
      " / " +
      String(fixture.timeline.length).padStart(2, "0");
    elements.responseBanner.innerHTML = renderResponseStateBanner(
      state.responseState,
    );
    elements.timelineList.innerHTML = visible
      .map((event, index) =>
        renderTimelineEvent(event, index, index === state.selectedIndex),
      )
      .join("");
    elements.timelineEnd.innerHTML =
      state.activeIndex === fixture.timeline.length - 1
        ? '<span class="timeline-end__mark" aria-hidden="true">✓</span><div><strong>证据链完整</strong><p>只有权威验证通过后，运行才显示 RESOLVED。</p></div>'
        : '<span class="timeline-end__mark timeline-end__mark--pending" aria-hidden="true"></span><div><strong>回放进行中</strong><p>下一步仍可能改变结论。</p></div>';
    elements.stepBack.disabled = state.activeIndex === 0;
    elements.stepForward.disabled =
      state.activeIndex === fixture.timeline.length - 1;
    elements.autoplay.classList.toggle("is-playing", state.playing);
    elements.autoplay.setAttribute(
      "aria-label",
      state.playing ? "暂停回放" : "自动回放",
    );
    renderTabs(state.panel);
    renderDetail();
    elements.provenance.innerHTML = renderProvenance(fixture);
  }

  function stopPlayback() {
    if (state.timer) window.clearInterval(state.timer);
    state.timer = null;
    state.playing = false;
  }

  function selectStep(index, options = {}) {
    state.activeIndex = clampStep(index, fixture.timeline.length);
    state.selectedIndex = state.activeIndex;
    if (!options.keepPlaying) stopPlayback();
    render();
    const selected = document.querySelector(
      '[data-event-index="' + state.selectedIndex + '"]',
    );
    if (options.focus && selected) selected.focus({ preventScroll: true });
    if (options.scroll && selected) {
      selected.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  function startPlayback() {
    if (state.playing) {
      stopPlayback();
      render();
      return;
    }
    if (state.activeIndex === fixture.timeline.length - 1) {
      state.activeIndex = 0;
      state.selectedIndex = 0;
    }
    state.playing = true;
    render();
    state.timer = window.setInterval(() => {
      if (state.activeIndex >= fixture.timeline.length - 1) {
        stopPlayback();
        render();
        return;
      }
      selectStep(state.activeIndex + 1, {
        keepPlaying: true,
        scroll: true,
      });
    }, 1150);
  }

  document.addEventListener("click", (event) => {
    const eventButton = event.target.closest("[data-event-index]");
    if (eventButton) {
      state.selectedIndex = Number(eventButton.dataset.eventIndex);
      state.panel = "evidence";
      stopPlayback();
      render();
      return;
    }
    const jumpButton = event.target.closest("[data-jump-index]");
    if (jumpButton) {
      selectStep(Number(jumpButton.dataset.jumpIndex), {
        focus: true,
        scroll: true,
      });
      return;
    }
    const panelButton = event.target.closest("[data-panel]");
    if (panelButton) {
      state.panel = panelButton.dataset.panel;
      render();
      return;
    }
    const approvalButton = event.target.closest("[data-approval-state]");
    if (approvalButton) {
      const next = approvalButton.dataset.approvalState;
      if (approvalStateOrder.includes(next)) {
        state.approvalState = next;
        render();
      }
      return;
    }
    const transitionButton = event.target.closest("[data-approval-transition]");
    if (transitionButton) {
      const next = transitionButton.dataset.approvalTransition;
      if (approvalStateOrder.includes(next)) {
        state.approvalState = next;
        render();
      }
      return;
    }
    const stateAction = event.target.closest("[data-state-action]");
    if (stateAction) {
      if (state.responseState === "safe-stop") {
        state.panel = "safety";
        state.approvalState = "denied";
      } else if (state.responseState === "resolved") {
        state.panel = "evidence";
        state.selectedIndex = fixture.timeline.findIndex(
          (item) => item.verification?.status === "passed",
        );
      } else {
        state.responseState = "resolved";
      }
      render();
    }
  });

  document.addEventListener("change", (event) => {
    if (event.target.matches("#response-state")) {
      const next = event.target.value;
      if (responseStateOrder.includes(next)) {
        state.responseState = next;
        render();
      }
    }
  });
  elements.stepBack.addEventListener("click", () =>
    selectStep(state.activeIndex - 1, { focus: true, scroll: true }),
  );
  elements.stepForward.addEventListener("click", () =>
    selectStep(state.activeIndex + 1, { focus: true, scroll: true }),
  );
  elements.replay.addEventListener("click", () =>
    selectStep(0, { scroll: true }),
  );
  elements.autoplay.addEventListener("click", startPlayback);
  window.addEventListener("beforeunload", stopPlayback);
  render();
}

function startLiveMode() {
  configureModeLabels({ live: true });
  const client = new IncidentPilotApiClient();
  const state = {
    runId: null,
    status: null,
    events: [],
    eventIds: new Map(),
    timeline: [],
    selectedIndex: 0,
    panel: "evidence",
    stream: null,
    pollTimer: null,
    streamConnected: false,
    streamEnded: false,
    artifacts: null,
    report: null,
    memory: null,
    approval: null,
    approvalMessage: "",
    contractError: "",
    busy: false,
  };

  elements.autoplay.disabled = true;
  elements.autoplay.setAttribute("aria-label", "实时模式会自动追加事件");

  function closeTransport() {
    state.stream?.close();
    state.stream = null;
    if (state.pollTimer) window.clearInterval(state.pollTimer);
    state.pollTimer = null;
    state.streamConnected = false;
  }

  function verifiedRecovery() {
    return !state.contractError && hasVerifiedRecovery(state.status, state.events, state.artifacts);
  }

  function effectiveStatus() {
    return liveDisplayStatus(state);
  }

  function publishDiagnostics() {
    const statusName = effectiveStatus();
    const lastSequence = state.events.at(-1)?.sequence ?? 0;
    window.__INCIDENTPILOT_C09__ = {
      source: "live-c08-sse",
      runId: state.runId,
      status: statusName,
      backendStatus: state.status?.status ?? "IDLE",
      lastSequence,
      eventIds: state.events.map((event) => event.event_id),
      timeline: state.timeline.map((event) => ({
        eventId: event.eventId,
        sequence: event.sequence,
        phase: event.phase,
        eventType: event.eventType,
        verification: event.verification?.status ?? null,
        newEvidence: event.newEvidence?.code ?? null,
      })),
      reportRunId: state.artifacts?.report?.run_id ?? null,
      memoryRunId: state.artifacts?.memory?.run_id ?? null,
      verifiedRecovery: verifiedRecovery(),
      contractError: state.contractError || null,
    };
    document.body.dataset.runStatus = statusName;
    document.body.dataset.runId = state.runId ?? "";
    document.body.dataset.lastSequence = String(lastSequence);
  }

  function renderDetail() {
    if (state.panel === "safety") {
      elements.detailContent.innerHTML = renderLiveApproval(
        state.approval,
        state.approvalMessage,
      );
      return;
    }
    if (state.panel === "report") {
      elements.detailContent.innerHTML = state.report
        ? renderReportPanel(state.report, {
            verifiedRecovery: verifiedRecovery(),
          })
        : renderLiveEmpty(
            "Report 尚未就绪",
            "只会在当前 live run 终止且后端制品门通过后读取。",
          );
      return;
    }
    if (state.panel === "memory") {
      elements.detailContent.innerHTML = state.memory
        ? renderMemoryPanel(state.memory, {
            verifiedRecovery: verifiedRecovery(),
          })
        : renderLiveEmpty(
            "Memory 尚未就绪",
            "页面不会从旧运行或 fixture 补全事故记忆。",
          );
      return;
    }
    const selected = state.timeline[state.selectedIndex];
    elements.detailContent.innerHTML = selected
      ? renderEvidencePanel(selected)
      : renderLiveEmpty(
          "等待第一条实时证据",
          "启动后，C08 SSE 中的原始事件会按 sequence 进入页面。",
        );
  }

  function render() {
    try {
      state.timeline = liveTimeline(state.events);
    } catch (error) {
      state.contractError = error.message;
      state.timeline = [];
    }
    if (state.timeline.length) {
      state.selectedIndex = clampStep(state.selectedIndex, state.timeline.length);
    } else {
      state.selectedIndex = 0;
    }
    const activeIndex = Math.max(0, state.timeline.length - 1);
    const phases = storyPhases(state.timeline);
    const verified = verifiedRecovery();
    const statusName = effectiveStatus();
    elements.incidentPanel.innerHTML = renderLiveIncident({
      status: state.status,
      timeline: state.timeline,
      verified,
      report: state.report,
      displayStatus: statusName,
    });
    elements.storyStrip.innerHTML = state.timeline.length
      ? renderStoryStrip(phases, activeIndex)
      : "";
    elements.storyProgress.textContent =
      String(state.timeline.length).padStart(2, "0") +
      " / " +
      String(state.timeline.length).padStart(2, "0");
    elements.responseBanner.innerHTML = renderLiveStatus(
      statusName,
      state.contractError,
    );
    elements.timelineList.innerHTML = state.timeline
      .map((event, index) =>
        renderTimelineEvent(event, index, index === state.selectedIndex),
      )
      .join("");
    if (verified) {
      elements.timelineEnd.innerHTML =
        '<span class="timeline-end__mark" aria-hidden="true">✓</span><div><strong>实时证据链完整</strong><p>权威验证、后端终态、Report 与 Memory 均来自这一 run。</p></div>';
    } else if (terminalRunStates.includes(state.status?.status)) {
      elements.timelineEnd.innerHTML =
        '<span class="timeline-end__mark timeline-end__mark--pending" aria-hidden="true"></span><div><strong>运行已终止，但未建立恢复</strong><p>界面保留已收证据，不会把动作结果当作 RESOLVED。</p></div>';
    } else {
      elements.timelineEnd.innerHTML =
        '<span class="timeline-end__mark timeline-end__mark--pending" aria-hidden="true"></span><div><strong>实时证据仍在追加</strong><p>下一条后端事件仍可能改变当前判断。</p></div>';
    }
    elements.stepBack.disabled =
      !state.timeline.length || state.selectedIndex === 0;
    elements.stepForward.disabled =
      !state.timeline.length ||
      state.selectedIndex >= state.timeline.length - 1;
    renderTabs(state.panel);
    renderDetail();
    elements.provenance.innerHTML = renderLiveProvenance({
      runId: state.runId,
      status: statusName,
      lastSequence: state.events.at(-1)?.sequence ?? 0,
      connected: state.streamConnected,
    });
    publishDiagnostics();
  }

  function appendEvent(event) {
    if (!appendLiveTraceEvent(state.events, state.eventIds, event)) return;
    state.selectedIndex = Math.max(0, liveTimeline(state.events).length - 1);
    render();
  }

  async function refreshStatus() {
    const runId = state.runId;
    if (!runId) return;
    const status = await client.getStatus(runId);
    if (state.runId !== runId) return;
    if (terminalRunStates.includes(state.status?.status) && activeRunStates.includes(status.status)) return;
    state.status = status;
    state.approval = status.pending_approvals[0] ?? null;
    if (state.approval) state.panel = "safety";
    render();
  }

  async function finishFromStream(end) {
    closeTransport();
    await refreshStatus();
    assertSealedTerminalTrace(state.events, end, state.status);
    if (state.status.report_available || state.status.memory_available) {
      if (!(state.status.report_available && state.status.memory_available)) {
        throw new Error("Report 与 Memory 必须作为同一制品对就绪。");
      }
      const [reportEnvelope, memoryEnvelope] = await Promise.all([
        client.getReport(state.runId),
        client.getMemory(state.runId),
      ]);
      state.artifacts = assertArtifactPair(
        reportEnvelope,
        memoryEnvelope,
        state.runId,
      );
      state.report = reportView(state.artifacts.report);
      state.memory = memoryView(state.artifacts.memory);
    }
    if (state.status.status === "RESOLVED" && !verifiedRecovery()) {
      throw new Error("后端 RESOLVED 未满足前端权威验证与同 run 制品门。");
    }
    state.streamEnded = true;
    closeTransport();
    render();
  }

  function startPolling() {
    const tick = async () => {
      try {
        await refreshStatus();
        if (terminalRunStates.includes(state.status.status)) {
          if (state.pollTimer) window.clearInterval(state.pollTimer);
          state.pollTimer = null;
        }
      } catch (error) {
        state.contractError = error.message;
        closeTransport();
        render();
      }
    };
    state.pollTimer = window.setInterval(tick, 400);
    tick();
  }

  function openStream() {
    state.stream = client.streamEvents(state.runId, {
      after: () => state.events.at(-1)?.sequence ?? 0,
      onEvent(event) {
        try {
          appendEvent(event);
        } catch (error) {
          state.contractError = error.message;
          closeTransport();
          render();
        }
      },
      onEnd(end) {
        finishFromStream(end).catch((error) => {
          state.contractError = error.message;
          closeTransport();
          render();
        });
      },
      onConnection(connection) {
        state.streamConnected = connection.connected;
        render();
      },
      onFailure(error) {
        state.contractError = error.message;
        closeTransport();
        render();
      },
    });
  }

  async function startRun() {
    if (state.busy || activeRunStates.includes(state.status?.status)) return;
    if (state.runId && !state.streamEnded && !state.contractError) return;
    closeTransport();
    Object.assign(state, {
      runId: null,
      status: { status: "STARTING", event_count: 0 },
      events: [],
      eventIds: new Map(),
      timeline: [],
      selectedIndex: 0,
      panel: "evidence",
      streamEnded: false,
      artifacts: null,
      report: null,
      memory: null,
      approval: null,
      approvalMessage: "",
      contractError: "",
      busy: true,
    });
    render();
    try {
      const accepted = await client.startRun();
      state.runId = accepted.run_id;
      state.status = {
        ...accepted,
        event_count: 0,
        pending_approvals: [],
      };
      state.busy = false;
      openStream();
      startPolling();
      render();
    } catch (error) {
      state.busy = false;
      state.contractError = error.message;
      render();
    }
  }

  async function cancelRun() {
    if (!state.runId || !activeRunStates.includes(state.status?.status)) return;
    try {
      state.status = await client.cancelRun(state.runId);
      state.approval = null;
      state.approvalMessage =
        "运行取消已请求；未使用授权将撤销。";
      render();
    } catch (error) {
      state.contractError = error.message;
      render();
    }
  }

  async function approvePending() {
    if (!state.runId || !state.approval) return;
    try {
      const requestId = state.approval.approval_request_id;
      await client.confirmApproval(state.runId, state.approval);
      state.approvalMessage =
        requestId +
        " 已精确批准；仍等待 ExecutionGuard 和权威验证。";
      state.approval = null;
      await refreshStatus();
    } catch (error) {
      state.approvalMessage = error.message;
      render();
    }
  }

  function selectStep(index, options = {}) {
    if (!state.timeline.length) return;
    state.selectedIndex = clampStep(index, state.timeline.length);
    state.panel = "evidence";
    render();
    const selected = document.querySelector(
      '[data-event-index="' + state.selectedIndex + '"]',
    );
    if (options.focus && selected) selected.focus({ preventScroll: true });
    if (options.scroll && selected) {
      selected.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  document.addEventListener("click", (event) => {
    const eventButton = event.target.closest("[data-event-index]");
    if (eventButton) {
      selectStep(Number(eventButton.dataset.eventIndex));
      return;
    }
    const jumpButton = event.target.closest("[data-jump-index]");
    if (jumpButton) {
      selectStep(Number(jumpButton.dataset.jumpIndex), {
        focus: true,
        scroll: true,
      });
      return;
    }
    const panelButton = event.target.closest("[data-panel]");
    if (panelButton) {
      state.panel = panelButton.dataset.panel;
      render();
      return;
    }
    if (event.target.closest("[data-live-approve]")) {
      approvePending();
      return;
    }
    const liveAction =
      event.target.closest("[data-live-action]")?.dataset.liveAction;
    if (liveAction === "start") startRun();
    if (liveAction === "cancel") cancelRun();
    if (liveAction === "report") {
      state.panel = "report";
      render();
    }
    if (liveAction === "evidence") {
      state.panel = "evidence";
      state.selectedIndex = Math.max(0, state.timeline.length - 1);
      render();
    }
  });

  elements.stepBack.addEventListener("click", () =>
    selectStep(state.selectedIndex - 1, { focus: true, scroll: true }),
  );
  elements.stepForward.addEventListener("click", () =>
    selectStep(state.selectedIndex + 1, { focus: true, scroll: true }),
  );
  elements.replay.addEventListener("click", () =>
    selectStep(0, { scroll: true }),
  );
  document.addEventListener("keydown", (event) => {
    if (
      event.target.matches("input, select, textarea, button") ||
      event.altKey ||
      event.ctrlKey ||
      event.metaKey
    ) {
      return;
    }
    if (event.key === "ArrowLeft") selectStep(state.selectedIndex - 1);
    if (event.key === "ArrowRight") selectStep(state.selectedIndex + 1);
  });
  window.addEventListener("beforeunload", closeTransport);
  render();
}

const mode = new URLSearchParams(window.location.search).get("mode");
if (mode === "recorded") {
  startRecordedMode();
} else {
  startLiveMode();
}
