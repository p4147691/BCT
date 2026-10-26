"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const monitor = fs.readFileSync(path.join(root, "extension", "monitor.js"), "utf8");
const publish = fs.readFileSync(path.join(__dirname, "Publish-MonitorDeployment.ps1"), "utf8");
const request = fs.readFileSync(path.join(__dirname, "Request-MonitorDeploymentCheck.ps1"), "utf8");
const structure = fs.readFileSync(path.join(__dirname, "check_monitor_structure.py"), "utf8");

const start = monitor.indexOf("async function checkMonitorDeploymentUpdate()");
const end = monitor.indexOf("// Desktop selection is synchronized", start);
assert(start > 0 && end > start, "deployment update function must remain indexable");
const update = monitor.slice(start, end);

assert.match(update, /const versionMismatch = Boolean/);
assert.match(update, /type: "monitor-reload-extension"/);
assert.ok(update.indexOf("if (versionMismatch)") < update.indexOf("ackExtensionReload"),
  "a stale loaded version must request a real reload before it can ACK");
assert.match(update, /reloadToken && reloadToken !== monitorReloadToken/);
assert.match(update, /return;[\s\S]*?ackExtensionReload/,
  "changed token branch must return without allowing the stale renderer to ACK");
assert.match(update, /monitorInitialThumbBatchDone[\s\S]*?ackExtensionReload/,
  "reload ACK must wait for the initial thumbnail acceptance gate");
assert.match(update, /monitorReloadAckToken !== reloadToken/,
  "the same accepted reload token is acknowledged at most once per runtime");

for (const source of [publish, request]) {
  assert.match(source, /shared-runtime\.json/);
  assert.match(source, /__MONITOR_INSTANCE__:GOOGLE/);
  assert.match(source, /manifest_version/);
  assert.match(source, /reload_token/);
  assert.match(source, /seen_at_ms/);
  assert.match(source, /runtime=verified/);
}

assert.ok((publish.match(/Invoke-MonitorStructureGate/g) || []).length >= 3,
  "publish must run the dependency gate before and after its manifest write");
assert.match(structure, /monitor_ui_layout_dependency_contract_broken/);
assert.match(structure, /choose_capture_view_declared/);
assert.match(structure, /layout_script_loaded_before_monitor/);
assert.match(structure, /layout_stylesheet_loaded/);
assert.match(structure, /renderer_has_nonthrowing_fallback/);

console.log("PASS: Monitor deployment requires a real reload and fresh exact-version runtime telemetry");
