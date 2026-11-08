"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const extensionRoot = path.join(__dirname, "..", "extension");
const shellSource = fs.readFileSync(path.join(extensionRoot, "monitor-bct-shell.js"), "utf8");
const featureSource = fs.readFileSync(path.join(extensionRoot, "features", "rcc-command-catalog", "monitor-rcc-command-catalog.js"), "utf8");
const bundleSource = fs.readFileSync(path.join(extensionRoot, "monitor.js"), "utf8");
const catalog = [{
  command: "rcc_get_extension_state", origin: "rcc-native", group: "status-and-targets",
  display_group: "상태·대상", summary: "RCC 확장 상태를 읽습니다.", effect: "조회만",
  target: "RCC 인스턴스", source: "modules/rcc/extension", legacy_alias: "state",
  compatibility_alias: "rcc_state",
}];

const context = { globalThis: null, fetch: async (url, init) => {
  assert.equal(url, "http://127.0.0.1:18790/monitor/rcc-command-catalog");
  assert.equal(init.cache, "no-store");
  return { ok: true, status: 200, json: async () => ({ schema: 1, commands: catalog }) };
} };
context.globalThis = context;
vm.createContext(context);
vm.runInContext(shellSource, context);
vm.runInContext(featureSource, context);

(async () => {
  const rows = await context.MonitorBctShell.create().rccCommandCatalog();
  assert.equal(rows.length, 1);
  assert.equal(rows[0].command, "rcc_get_extension_state");
  assert.ok(Object.isFrozen(rows[0]));
  const normalized = context.MonitorRccCommandCatalog.normalizeRows([...rows, { command: "bad", origin: "bct" }]);
  assert.equal(normalized.length, 1);
  assert.equal(normalized[0].group, "상태·대상");
  assert.equal(normalized[0].origin, "rcc-native");
  assert.ok(Object.isFrozen(normalized));
  assert.match(bundleSource, /id="monitorCommandCatalogOpen"[^>]*>명령 목록/);
  assert.match(bundleSource, /id="monitorCommandCatalogDialog"/);
  assert.ok(bundleSource.indexOf('id="monitorBctControlRefresh"') < bundleSource.indexOf('id="monitorCommandCatalogOpen"'));
  assert.doesNotMatch(bundleSource, /monitor-command-catalog-section/);
  assert.match(featureSource, /async function open\(\)/);
  assert.match(featureSource, /dialog\.showModal\(\)/);
  console.log("PASS: Monitor reads and presents the authoritative command catalogue without command execution.");
})().catch((error) => { console.error(error); process.exitCode = 1; });
