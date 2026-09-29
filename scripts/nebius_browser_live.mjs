import {spawn} from "node:child_process";
import {existsSync} from "node:fs";
import {mkdir, readFile, writeFile, rm} from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

const root = process.cwd();
const output = path.join(root, "runtime/nebius/browser-live");
const profile = path.join(output, "profile-" + Date.now());
const base = "http://127.0.0.1:4180";
const recording = true;
const videoDir = path.join(root, "runtime/nebius/video-live");
const framesDir = path.join(videoDir, "frames-" + Date.now());
if (recording) await mkdir(framesDir, {recursive: true});
await mkdir(profile, {recursive: true});
const executable = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find(existsSync);
assert.ok(executable, "Chrome/Edge required");
const chrome = spawn(executable, ["--headless=new", "--remote-debugging-port=0", "--user-data-dir=" + profile,
  "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "about:blank"], {windowsHide: true, stdio: "ignore"});
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, timeout = 15000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const result = await fn(); if (result) return result; await sleep(100); }
  throw new Error("Browser condition timed out");
}
let socket;
let frameTimer, capturing = false, frameNumber = 0;
try {
  const active = await until(async () => { try { return await readFile(path.join(profile, "DevToolsActivePort"), "utf8"); } catch {return null;} });
  const [port] = active.trim().split("\n");
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve); socket.addEventListener("error", reject); });
  let sequence = 0; const pending = new Map(); const errors = [];
  socket.addEventListener("message", ({data}) => {
    const message = JSON.parse(String(data));
    if (message.method === "Runtime.exceptionThrown") errors.push(message.params.exceptionDetails.text);
    if (!message.id) return;
    const callback = pending.get(message.id); if (!callback) return;
    pending.delete(message.id); message.error ? callback.reject(Error(message.error.message)) : callback.resolve(message.result);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence; pending.set(id, {resolve, reject}); socket.send(JSON.stringify({id, method, params}));
  });
  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", {expression, awaitPromise: true, returnByValue: true});
    if (result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  const screenshot = async (name) => {
    const result = await send("Page.captureScreenshot", {format: "png"});
    await writeFile(path.join(output, name), Buffer.from(result.data, "base64"));
  };
  await send("Runtime.enable"); await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", {width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false});
  await send("Page.navigate", {url: base});
  await until(() => evaluate("document.querySelector('#case')?.options.length > 0"));
  const caption = async (value) => evaluate(`(() => {
    let caption = document.getElementById('video-caption');
    if (!caption) { caption = document.createElement('div'); caption.id='video-caption';
      caption.style.cssText='position:fixed;bottom:12px;left:5%;right:5%;padding:16px 22px;background:#101010;color:white;border-radius:10px;z-index:99999;font:18px/1.5 Segoe UI,sans-serif;box-shadow:0 2px 20px #0003;text-align:center';document.body.append(caption); }
    caption.textContent=${JSON.stringify(value)};
  })()`);
  if (recording) {
    await caption("IncidentPilot: live Nemotron on Nebius investigates real project-owned test services. This is a test environment, not a connected enterprise system.");
    frameTimer = setInterval(async () => {
      if (capturing) return; capturing = true;
      try {
        const shot = await send("Page.captureScreenshot", {format: "jpeg", quality: 88});
        await writeFile(path.join(framesDir, String(frameNumber++).padStart(5,"0")+".jpg"), Buffer.from(shot.data,"base64"));
      } finally { capturing = false; }
    }, 500);
    await sleep(6500);
  }
  await screenshot("desktop-ready.png");
  const checks = [];
  const before = await (await fetch(base + '/api/v2/config')).json();
  assert.ok(before.allow_live && before.key_present, 'Live server/key required');
  assert.ok(before.budget.remaining_under_ceiling_usd >= 0.15, 'Reserve for two bounded runs');
  for (const [system, testCase, expected] of [
    ['http-app', 'http-stopped', 'RESOLVED'],
    ['background-jobs', 'job-locked', 'RESOLVED'],
  ]) {
    if (recording) await caption({
      "http-stopped": "A real HTTP listener has stopped. Choose the system, describe the symptom, then investigate.",
      "http-dependency": "Same symptom, different cause. Restart succeeds, but the actual HTTP business check still fails. No false recovery.",
      "job-transient": "A real background worker failed. Retry recomputes its task output; verification checks the current job and result.",
      "job-locked": "An orphaned lock blocks the task. Nemotron must investigate logs, choose a permitted repair, and verify actual task output.",
      "permission-missing": "Missing repair permission: keep the evidence and hand the incident to a human. No mutation is executed.",
      "evidence-missing": "Missing evidence: stop guessing. The report says recovery is unverified and asks for human help.",
    }[testCase]);
    await evaluate(`document.querySelector('#system').value=${JSON.stringify(system)}; document.querySelector('#system').dispatchEvent(new Event('change')); document.querySelector('#case').value=${JSON.stringify(testCase)}; document.querySelector('#case').dispatchEvent(new Event('change')); document.querySelector('#mode').value='live'; document.querySelector('#mode').dispatchEvent(new Event('change')); document.querySelector('#start').click();`);
    await until(() => evaluate("document.querySelector('#start').disabled"));
    await until(() => evaluate("!document.querySelector('#start').disabled && document.querySelectorAll('.answer-card').length===4"), 240000);
    const report = await (await fetch(base + "/api/v2/report")).json();
    assert.equal(report.status, expected); assert.equal(report.mode, "live");
    assert.ok(!report.error && report.cost.requests > 0);
    assert.ok(report.events.some(e => e.type === "tool.requested" && e.data.origin === "provider"));
    assert.equal(report.verification.status, "PASSED");
    assert.equal(await evaluate("document.querySelector('#run-badge').textContent"), expected);
    checks.push({case: testCase, expected, actual: report.status, run_id: report.run_id});
    if (testCase === "http-stopped") await screenshot("desktop-recovered.png");
    if (recording) await sleep(6500);
  }
  await screenshot("desktop-handoff.png");
  await evaluate("document.querySelector('#history').closest('details').open=true; document.querySelector('#history button').click()");
  await until(() => evaluate("document.querySelector('#run-badge').textContent==='RECORDED'"));
  if (recording) {
    await caption("One report preserves the evidence, actions and independent checks. History is visibly RECORDED. The preceding investigations ran live through the page. This view now shows history; no new action is running.");
    await sleep(6500);
    clearInterval(frameTimer); frameTimer = null;
    await until(() => !capturing);
    await writeFile(path.join(videoDir,"capture.json"), JSON.stringify({mode:"live-browser", frames:frameNumber,
      fps:2, frames_directory:framesDir, note:"Actual live browser investigations on owned test services; English captions; history explicitly labelled."},null,2));
    await evaluate("document.getElementById('video-caption').remove()");
  }
  await evaluate("document.querySelector('#language').click()");
  await send("Emulation.setDeviceMetricsOverride", {width: 430, height: 932, deviceScaleFactor: 1, mobile: true});
  await screenshot("mobile-430.png");
  assert.ok(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "No horizontal overflow");
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "check.json"), JSON.stringify({status: "PASS", mode: "live-browser", budget_before: before.budget, budget_after: (await (await fetch(base + "/api/v2/config")).json()).budget,
    cases: checks, recording_label: true, language_toggle: true, mobile_overflow: false, javascript_errors: errors}, null, 2));
  console.log(JSON.stringify({status: "PASS", cases: checks.length, screenshots: output}));
  await send("Browser.close");
} finally {
  if (frameTimer) clearInterval(frameTimer);
  socket?.close();
  await sleep(500);
  if (chrome.exitCode === null) chrome.kill();
  await sleep(500);
  // Only remove this script's newly created profile within its exact runtime directory.
  assert.equal(path.dirname(path.resolve(profile)), path.resolve(output));
  await rm(profile, {recursive: true, force: true, maxRetries: 5, retryDelay: 300});
}
