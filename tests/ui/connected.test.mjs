import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../../ui/src/api/connected.js", import.meta.url), "utf8");
const budget = { estimated_usd: 0, unconfirmed_upper_usd: 0, ceiling_usd: 0.8 };
const idle = { busy: false, mode: null, events: [], budget, report: null, error: null };
const busy = (mode = "live") => ({ ...idle, busy: true, mode });

async function browser({ initialState = idle, postError = null, rejectPost = false, failedReads = 0, deferCancel = false } = {}) {
  const elements = new Map();
  const timers = new Map();
  const calls = [];
  let state = initialState, nextTimer = 0, remainingFailedReads = 0;
  let releaseCancel;
  function element(tag = "div") {
    return {
      tag, value: "", textContent: "", disabled: false, hidden: false, dataset: {},
      options: [{}], children: [], listeners: {},
      classList: { add() {}, toggle() {} },
      replaceChildren(...children) { this.children = children; if (tag === "select") this.value = children[0]?.value || ""; },
      append(...children) { this.children.push(...children); if (tag === "select" && !this.value) this.value = children[0]?.value || ""; },
      addEventListener(name, callback) { this.listeners[name] = callback; },
    };
  }
  function get(id) {
    if (!elements.has(id)) elements.set(id, element(["system", "case", "mode"].includes(id) ? "select" : "div"));
    return elements.get(id);
  }
  get("system").value = "http-app";
  get("mode").value = "live";
  const response = (value, ok = true) => ({ ok, json: async () => value });
  await vm.runInNewContext(`(async () => {${source}\n})()`, {
    document: { getElementById: get, createElement: element, querySelectorAll: () => [], documentElement: {} },
    Blob,
    URL: { createObjectURL: () => "blob:test-report", revokeObjectURL() {} },
    setTimeout(callback) { timers.set(++nextTimer, callback); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
    async fetch(path, options = {}) {
      const endpoint = path.slice("/api/v2/".length);
      calls.push({ endpoint, method: options.method || "GET", body: options.body && JSON.parse(options.body) });
      if (endpoint === "config") return response({ allow_live: true, key_present: true, model: "test-model", budget,
        cases: { "http-stopped": { system: "http-app", description: "Service unavailable" } } });
      if (endpoint === "history") return response([]);
      if (endpoint === "cancel") {
        if (deferCancel) return new Promise(resolve => { releaseCancel = () => resolve(response({ cancel_requested: true })); });
        return response({ cancel_requested: true });
      }
      if (endpoint === "run" && options.method === "POST") {
        if (rejectPost) return response({ error: "Submission rejected" }, false);
        state = busy(JSON.parse(options.body).mode);
        remainingFailedReads = failedReads;
        if (postError) throw new TypeError(postError);
        return response({ accepted: true });
      }
      if (endpoint === "run") {
        if (remainingFailedReads-- > 0) throw new TypeError("Connection unavailable");
        return response(state);
      }
      throw new Error(`Unexpected request: ${endpoint}`);
    },
  });
  return {
    get, calls, timers,
    setState(next) { state = next; },
    submit() { return get("investigation-form").listeners.submit({ preventDefault() {} }); },
    cancel() { return get("cancel").listeners.click(); },
    releaseCancel() { releaseCancel(); },
    async tick() {
      const [id, callback] = timers.entries().next().value || [];
      assert.ok(callback, "a status retry should be scheduled");
      timers.delete(id);
      await callback();
    },
  };
}

function assertControls(page, running, canCancel = running) {
  for (const id of ["system", "case", "description", "mode", "start"]) {
    assert.equal(page.get(id).disabled, running, `${id} lock follows the confirmed run state`);
  }
  assert.equal(page.get("cancel").disabled, !canCancel);
}

test("an accepted submission with a lost response resumes tracking without a second POST", async () => {
  const page = await browser({ postError: "Response lost" });
  await page.submit();
  assertControls(page, true);
  assert.equal(page.get("run-badge").textContent, "LIVE");
  assert.equal(page.calls.filter(call => call.endpoint === "run" && call.method === "POST").length, 1);
  assert.equal(page.calls.at(-1).method, "GET");
  assert.equal(page.calls.at(-1).endpoint, "run");
  assert.equal(page.timers.size, 1);
});

test("connection loss after an uncertain submission keeps controls locked until status recovers", async () => {
  const page = await browser({ postError: "Response lost", failedReads: 2 });
  await page.submit();
  assertControls(page, true);
  assert.match(page.get("status").textContent, /Reconnecting/);
  await page.tick();
  assertControls(page, true);
  await page.tick();
  assertControls(page, true);
  assert.equal(page.get("run-badge").textContent, "LIVE");
  assert.equal(page.calls.filter(call => call.method === "POST").length, 1);
});

test("a rejected submission unlocks the form only after confirming the server is idle", async () => {
  const page = await browser({ rejectPost: true });
  await page.submit();
  assertControls(page, false);
  assert.equal(page.get("status").textContent, "Submission rejected");
  assert.equal(page.timers.size, 0);
  const post = page.calls.findIndex(call => call.method === "POST");
  assert.equal(page.calls[post + 1].endpoint, "run");
  assert.equal(page.calls[post + 1].method, "GET");
});

test("a busy run uses the server mode even if the form value changes", async () => {
  const page = await browser();
  await page.submit();
  page.get("mode").value = "offline-test";
  await page.tick();
  assertControls(page, true);
  assert.equal(page.get("run-badge").textContent, "LIVE");
  assert.equal(page.get("mode").value, "live");
});

test("refresh restores an offline run instead of displaying the default live label", async () => {
  const page = await browser({ initialState: busy("offline-test") });
  assertControls(page, true);
  assert.equal(page.get("mode").value, "offline-test");
  assert.equal(page.get("run-badge").textContent, "OFFLINE TEST");
  assert.match(page.get("mode-note").textContent, /No model calls/);
  assert.equal(page.calls.filter(call => call.method === "POST").length, 0);
});

test("an unavailable mode is not reported as a known offline run", async () => {
  const page = await browser({ initialState: busy(null) });
  assertControls(page, true);
  assert.equal(page.get("run-badge").textContent, "RUNNING");
});

test("completion after reconnection renders the report and unlocks the form", async () => {
  const page = await browser({ postError: "Response lost" });
  await page.submit();
  page.setState({ ...idle, report: { run_id: "RUN-TEST", mode: "live", status: "RESOLVED", verified: true,
    summary: { problem: "Unavailable", work_done: "Restarted", next_step: "None" } } });
  await page.tick();
  assertControls(page, false);
  assert.equal(page.get("run-badge").textContent, "RESOLVED");
  assert.equal(page.get("status").textContent, "RUN-TEST");
  assert.equal(page.get("download").hidden, false);
  assert.equal(page.timers.size, 0);
});

test("polling preserves a pending stop request until the run completes", async () => {
  const page = await browser();
  await page.submit();
  await page.cancel();
  await page.tick();
  assertControls(page, true, false);
  page.setState(idle);
  await page.tick();
  assertControls(page, false);
});


test("a delayed stop response from a completed run cannot disable the next run's stop button", async () => {
  const page = await browser({ deferCancel: true });
  await page.submit();
  const previousCancel = page.cancel();
  page.setState(idle);
  await page.tick();
  assertControls(page, false);
  await page.submit();
  assertControls(page, true);
  page.releaseCancel();
  await previousCancel;
  assertControls(page, true);
  await page.tick();
  assertControls(page, true);
});
