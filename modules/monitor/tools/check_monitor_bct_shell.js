"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "extension", "monitor-bct-shell.js"),
  "utf8",
);
const monitorSource = fs.readFileSync(
  path.join(__dirname, "..", "extension", "monitor.js"),
  "utf8",
);
const desktopSource = fs.readFileSync(
  path.join(__dirname, "..", "extension", "desktop.html"),
  "utf8",
);
const manifest = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "extension", "manifest.json"),
  "utf8",
));
const opened = [];
const context = {
  globalThis: null,
  fetch: async (url, init) => {
    assert.equal(url, "http://127.0.0.1:18790/health");
    assert.equal(init?.cache, "no-store");
    return {
      ok: true,
      status: 200,
      async json() {
        return { status: "OK", ready: true, service: "bct-core", release_sha: "a".repeat(40), generation: 3, pid: 42 };
      },
    };
  },
  chrome: {
    windows: {
      async create(value) {
        opened.push(value);
        return { id: opened.length };
      },
    },
  },
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context);

(async () => {
  assert.equal(manifest.name, "BCT Window Monitor");
  assert.equal(manifest.version, "2.0.0");
  assert.ok(desktopSource.indexOf("monitor-bct-shell.js") < desktopSource.indexOf("monitor.js"));
  assert.match(monitorSource, /id="monitorBctOpen"/);
  assert.match(monitorSource, /id="monitorLocalLlmOpen"/);
  assert.doesNotMatch(monitorSource, /id="monitorActRestart"/);
  assert.doesNotMatch(monitorSource, /id="monitorNodeSync"/);
  assert.match(monitorSource, /const MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED = false;/);
  assert.match(monitorSource, /const MONITOR_NODE_RENDER_ENABLED = false;/);
  assert.match(monitorSource, /monitor-ai-section" hidden/);
  const shell = context.MonitorBctShell.create();
  const health = await shell.health();
  assert.equal(health.service, "bct-core");
  assert.equal(health.generation, 3);
  await shell.openStatus();
  await shell.openLocalLlm();
  assert.deepEqual(
    opened.map((value) => value.url),
    ["http://127.0.0.1:18790/monitor", "http://127.0.0.1:18790/monitor#local-llm"],
  );
  assert.ok(opened.every((value) => value.type === "popup" && value.focused === true));
  console.log("PASS: BCT health and explicit BCT/Laya status boundaries");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
