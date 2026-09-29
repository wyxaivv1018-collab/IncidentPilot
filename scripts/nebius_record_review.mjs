import {spawn} from "node:child_process";
import {existsSync} from "node:fs";
import {mkdir, readFile, writeFile, rm} from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

const root = process.cwd();
const output = path.join(root, "runtime/nebius/browser-live-review");
const profile = path.join(output, "profile-" + Date.now());
const base = "http://127.0.0.1:4180";
const recording = true;
const videoDir = path.join(root, "runtime/nebius/video-live-review");
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
    await caption("IncidentPilot investigates incidents with NVIDIA Nemotron on Nebius. This video reviews recorded REAL model runs; no new operation is running.");
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
  const comparison = JSON.parse(await readFile(path.join(root, "runtime/nebius/comparison-live.json"), "utf8"));
  const notes = {
    "http-stopped": "A stopped HTTP service: the model chooses a restart. A fresh business request verifies recovery.",
    "http-dependency": "Same unavailable-app symptom, different cause: model chooses dependency repair instead of a restart.",
    "job-transient": "Background task failure: a real worker recomputes output. The check validates this job's actual result.",
    "job-locked": "Changed task cause: model reads log evidence, releases an orphaned lock and retries. Unlocking alone is not recovery.",
    "permission-missing": "No repair permission: evidence is preserved and handed to a human. No action executes.",
    "evidence-missing": "No readable monitoring evidence: the agent hands off without guessing or reporting recovery."
  };
  for (const [testCase, note] of Object.entries(notes)) {
    const row = comparison.results.find(r => r.case === testCase && r.method === "incidentpilot");
    assert.ok(row && row.mode === "live");
    await caption("RECORDED REAL RUN: " + note);
    await evaluate(`(async () => {
      const report = await (await fetch('/api/v2/history/${row.run_id}')).json();
      document.querySelector('#history').closest('details').open = true;
      const buttons = [...document.querySelectorAll('#history button')];
      const button = buttons.find(b => b.textContent.includes('${row.run_id}'));
      if (!button) throw Error('Expected real report missing from history');
      button.click();
    })()`);
    await until(() => evaluate(`document.querySelector('#status').textContent.includes('${row.run_id}') && document.querySelector('#run-badge').textContent === 'RECORDED'`));
    await evaluate("document.querySelector('#history').closest('details').open = false; document.querySelector('#answer-cards').scrollIntoView({block:'center'})");
    await screenshot(testCase + '.png');
    checks.push({case: testCase, run_id:row.run_id, status:row.status, original_mode:row.mode, displayed_mode:'RECORDED'});
    await sleep(7500);
  }
  await caption("Observed value: adaptive recovery beyond a fixed SOP. Initial generic and IncidentPilot results tied; prompt repair improved the locked case. Small development sample, not a statistical win.");
  await sleep(8500);
  await caption("Model chooses tools; code enforces permissions, budget and independent verification. Public judge access and submission are pending. Existing project substantially updated for this event.");
  await sleep(7500);
  clearInterval(frameTimer); frameTimer = null;
  await until(() => !capturing);
  await writeFile(path.join(videoDir,'capture.json'), JSON.stringify({mode:'recorded-real-model-runs',frames:frameNumber,fps:2,frames_directory:framesDir,paid_calls_during_recording:0,note:'Actual browser footage reviewing real Nebius executions, always labelled RECORDED.',cases:checks},null,2));
  await evaluate("document.getElementById('video-caption').remove()");
  await evaluate("document.querySelector('#language').click()");
  await send("Emulation.setDeviceMetricsOverride", {width: 430, height: 932, deviceScaleFactor: 1, mobile: true});
  await screenshot("mobile-430.png");
  assert.ok(await evaluate("document.documentElement.scrollWidth <= innerWidth"), "No horizontal overflow");
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "check.json"), JSON.stringify({status: "PASS", mode: "recorded-real-model-runs", paid_calls: 0,
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
