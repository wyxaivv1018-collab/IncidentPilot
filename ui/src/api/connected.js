const $ = (id) => document.getElementById(id);
let config, timer, lastReport, recorded = false, lang = "en", downloadUrl;
let submissionError = null, cancelRequested = false, runToken = 0;
const text = (en, zh) => lang === "en" ? en : zh;
async function api(path, body) {
  const response = await fetch("/api/v2/" + path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Request failed");
  return value;
}
function setCases() {
  $("case").replaceChildren();
  for (const [name, spec] of Object.entries(config.cases)) {
    if (spec.system !== $("system").value) continue;
    const option = document.createElement("option"); option.value = name;
    option.textContent = name.replaceAll("-", " "); $("case").append(option);
  }
  $("description").value = config.cases[$("case").value].description;
}
function modeNote() {
  $("mode-note").textContent = $("mode").value === "live"
    ? text("Live model decisions; operations affect real, owned local test services.", "模型实时调查和选择工具；操作会实际影响本地测试服务。")
    : text("Fixed SOP on real test services. No model calls; this does not validate AI decisions.", "固定步骤操作真实测试服务，不调用模型，不能证明 AI 调查能力。") ;
}
function setBusy(busy) {
  for (const id of ["system", "case", "description", "mode"]) $(id).disabled = busy;
  $("start").disabled = busy;
  $("cancel").disabled = !busy || cancelRequested;
}
function renderBudget(budget) {
  $("budget").textContent = `Estimated $${budget.estimated_usd.toFixed(5)} · Unconfirmed ≤ $${budget.unconfirmed_upper_usd.toFixed(5)} · Cap $${budget.ceiling_usd.toFixed(2)}`;
}
function renderReport(report) {
  lastReport = report;
  $("run-badge").textContent = recorded ? "RECORDED" : report.mode === "live" ? report.status : "OFFLINE TEST";
  $("run-badge").dataset.state = report.status;
  $("status").textContent = (recorded ? text("Historical report. No operation is running. ", "历史报告，没有执行新操作。") : "") + report.run_id;
  const summary = report.summary;
  const entries = [
    [text("What went wrong", "哪里出问题"), summary.problem],
    [text("What happened", "已经做了什么"), summary.work_done],
    [text("Is it working?", "恢复没有"), report.verified
      ? text("Recovery verified against the actual service result.", "已检查实际服务结果，恢复验证通过。")
      : text("Recovery has not been verified. Human help is needed.", "尚未证明恢复，需要人工接手。")],
    [text("What you need to do", "需要我做什么"), summary.next_step],
  ];
  $("answer-cards").replaceChildren(...entries.map(([label, value]) => {
    const card = document.createElement("article"); card.className = "answer-card";
    const title = document.createElement("h3"); title.textContent = label;
    const body = document.createElement("p"); body.textContent = value;
    card.append(title, body); return card;
  }));
  $("evidence").textContent = JSON.stringify(report, null, 2);
  if (downloadUrl) URL.revokeObjectURL(downloadUrl);
  downloadUrl = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type: "application/json"}));
  $("download").href = downloadUrl; $("download").hidden = false;
  document.querySelectorAll(".connected-progress li").forEach((item) => item.classList.add("active"));
}
function renderEvents(events) {
  const visible = events.filter((e) => ["evidence.read", "decision.recorded", "action.executed", "action.denied", "verification.result", "run.error"].includes(e.type));
  $("timeline").replaceChildren(...visible.map((event) => {
    const row = document.createElement("div"); row.className = "connected-event";
    const label = document.createElement("small"); label.textContent = `${event.id} · ${event.type}`;
    const body = document.createElement("span");
    body.textContent = event.data.explanation || event.data.check || event.data.reason || event.data.action || event.data.source || event.data.category;
    if (event.data.status) body.textContent += ` → ${event.data.status}`;
    row.append(label, body); return row;
  }));
  $("evidence").textContent = JSON.stringify(events, null, 2);
}
async function history() {
  const rows = await api("history"); $("history").replaceChildren();
  for (const item of rows.reverse()) {
    const button = document.createElement("button"); button.type = "button";
    button.textContent = `${item.run_id} · ${item.mode} · ${item.status}`;
    button.addEventListener("click", async () => {
      if ($("start").disabled) return;
      const data = await api("history/" + item.run_id); recorded = true;
      renderEvents(data.report.events); renderReport(data.report);
    }); $("history").append(button);
  }
}
async function poll() {
  try {
    const state = await api("run"); renderBudget(state.budget);
    renderEvents(state.events);
    setBusy(state.busy);
    if (state.busy) {
      recorded = false;
      if (["live", "offline-test"].includes(state.mode)) {
        $("mode").value = state.mode; modeNote();
      }
      $("status").textContent = text("Investigating the running test service…", "正在调查实际运行的测试服务……");
      $("run-badge").textContent = state.mode === "live" ? "LIVE" : state.mode === "offline-test" ? "OFFLINE TEST" : "RUNNING";
      delete $("run-badge").dataset.state;
      timer = setTimeout(poll, 800);
    } else {
      runToken += 1; cancelRequested = false;
      if (state.report) renderReport(state.report);
      else if (state.error || submissionError) $("status").textContent = state.error || submissionError;
      else $("status").textContent = text("Choose a system and describe the symptom to begin.", "选择系统并描述故障，开始调查。");
      submissionError = null;
      await history();
    }
  } catch (error) {
    $("status").textContent = text("Connection interrupted. Reconnecting; no new run will start. ", "连接中断，正在重连，不会发起新运行。") + error.message;
    timer = setTimeout(poll, 2000);
  }
}
$("investigation-form").addEventListener("submit", async (event) => {
  event.preventDefault(); clearTimeout(timer); recorded = false; runToken += 1;
  submissionError = null; cancelRequested = false; setBusy(true);
  $("download").hidden = true;
  $("answer-cards").replaceChildren(); lastReport = null;
  document.querySelectorAll(".connected-progress li").forEach((item, i) => item.classList.toggle("active", i === 0));
  try {
    await api("run", {case: $("case").value, mode: $("mode").value, description: $("description").value});
    await poll();
  } catch (error) {
    submissionError = error.message;
    await poll();
  }
});
$("cancel").addEventListener("click", async () => {
  const requestRunToken = runToken;
  await api("cancel", {});
  if (requestRunToken !== runToken) return;
  cancelRequested = true; $("cancel").disabled = true;
});
$("system").addEventListener("change", setCases);
$("case").addEventListener("change", () => { $("description").value = config.cases[$("case").value].description; });
$("mode").addEventListener("change", modeNote);
$("language").addEventListener("click", () => {
  lang = lang === "en" ? "zh" : "en"; document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  document.querySelectorAll("[data-en]").forEach((el) => { el.textContent = el.dataset[lang]; });
  $("language").textContent = lang === "en" ? "中文" : "English"; modeNote();
  if (lastReport) renderReport(lastReport);
});
try {
  setBusy(true); $("cancel").disabled = true;
  config = await api("config"); setCases();
  if (!config.allow_live || !config.key_present) {
    $("mode").value = "offline-test"; $("mode").options[0].disabled = true;
  }
  $("configuration").textContent = `${config.model} · Key ${config.key_present ? "available" : "missing"}`;
  modeNote(); renderBudget(config.budget); await history();
  await poll();
} catch (error) { $("status").textContent = error.message; $("start").disabled = true; }
