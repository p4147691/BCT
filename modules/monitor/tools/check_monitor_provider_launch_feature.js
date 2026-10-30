"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const js = fs.readFileSync(path.resolve(__dirname, "../extension/monitor-provider-launch-feature.js"), "utf8");
const global = {};
vm.runInNewContext(js, { globalThis: global });
const feature = global.MonitorProviderLaunchFeature;
const html = fs.readFileSync(path.resolve(__dirname, "../extension/desktop.html"), "utf8");
const source = fs.readFileSync(path.resolve(__dirname, "../domains/diagnostics-shell.js"), "utf8");
const featureIndex = html.indexOf('src="monitor-provider-launch-feature.js"');
const bundleIndex = html.indexOf('src="monitor.js"');
assert.ok(featureIndex >= 0 && bundleIndex > featureIndex, "feature script must load before bundle");
assert.match(source, /MonitorProviderLaunchFeature[.]bind[(]/);

assert.equal(typeof feature.bind, "function");

function button() {
  const handlers = new Map();
  return {
    dataset: {}, disabled: true, title: "", textContent: "", handlers,
    setAttribute(key, value) { this[key] = value; },
    addEventListener(type, handler) { handlers.set(type, handler); },
    removeEventListener(type, handler) {
      if (handlers.get(type) === handler) handlers.delete(type);
    },
    click() { return handlers.get("click")?.(); },
  };
}
async function run() {
  const b = button(), launches = [], failures = [];
  const ports = {
    launch: async action => { launches.push(action.type); return { ok: true, launched: true }; },
    fail: message => failures.push(message),
  };
  const first = feature.bind({ button: b, provider: "google", ports });
  assert.equal(b.dataset.provider, "GOOGLE");
  assert.equal(b.textContent, "G+");
  await b.click();
  assert.deepEqual(launches, ["launchGoogleChatGpt"]);
  const second = feature.bind({ button: b, provider: "NAVER", ports });
  assert.equal(b.textContent, "N+");
  first.destroy();
  await b.click();
  assert.deepEqual(launches, ["launchGoogleChatGpt", "launchNaverChatGpt"]);
  second.destroy();
  assert.equal(b.handlers.has("click"), false);
  const failure = feature.bind({
    button: b, provider: "NAVER",
    ports: { launch: async () => ({ ok: false, error: "blocked" }), fail: message => failures.push(message) },
  });
  await b.click();
  assert.match(failures[0], /blocked/);
  failure.destroy();
  assert.throws(() => feature.bind({ button: b, ports: {} }), /injected/);
  console.log("PASS: isolated Header provider launch ownership, ports, rebinding and destroy");
}
run().catch(error => { console.error(error); process.exitCode = 1; });
