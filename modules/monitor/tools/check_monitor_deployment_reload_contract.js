"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const monitor = fs.readFileSync(path.join(root, "extension", "monitor.js"), "utf8");
const publish = fs.readFileSync(path.join(__dirname, "Publish-MonitorDeployment.ps1"), "utf8");
const request = fs.readFileSync(path.join(__dirname, "Request-MonitorDeploymentCheck.ps1"), "utf8");

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

for (const source of [publish, request]) {
  assert.match(source, /shared-runtime\.json/);
  assert.match(source, /__MONITOR_INSTANCE__:GOOGLE/);
  assert.match(source, /manifest_version/);
  assert.match(source, /reload_token/);
  assert.match(source, /seen_at_ms/);
  assert.match(source, /runtime=verified/);
}

console.log("PASS: Monitor deployment requires a real reload and fresh exact-version runtime telemetry");
