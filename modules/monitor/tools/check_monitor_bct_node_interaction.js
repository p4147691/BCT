"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const modulePath = path.join(root, "extension", "monitor-bct-node-interaction.js");
const monitorPath = path.join(root, "extension", "monitor.js");
const cssPath = path.join(root, "extension", "monitor.css");

function loadModule() {
  const context = { globalThis: null, Object, String, Number, Array, Error, RegExp, Promise };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(modulePath, "utf8"), context, { filename: modulePath });
  return context.MonitorBctNodeInteraction;
}

(async () => {
  const calls = [];
  const highlights = [];
  const renders = [];
  const selected = [];
  const nativeRequest = async (message) => {
    calls.push({ ...message });
    if (message.type === "getVirtualDesktops") return { ok: true, desktopIds: ["desk-a", "desk-b"] };
    if (message.type === "getDesktopWindowHandles" && message.desktopId === "desk-a") return { ok: true, hwnds: ["11"] };
    if (message.type === "getDesktopWindowHandles" && message.desktopId === "desk-b") return { ok: true, windows: [{ hwnd: "4242" }] };
    if (message.type === "switchVirtualDesktop") return { ok: true, desktopIds: ["desk-a", "desk-b"], selectedIndex: message.index };
    if (message.type === "restoreForegroundWindow") return { ok: true, hwnd: message.hwnd };
    return { ok: false, error: "UNEXPECTED_CALL" };
  };

  const service = loadModule().create({
    nativeRequest,
    highlight: (hwnd) => highlights.push(hwnd),
    renderVirtualDesktops: (state) => renders.push(state),
    selectVirtualDesktopPreview: (index) => selected.push(index),
  });
  const result = await service.activate("4242");
  assert.deepEqual({ ...result }, { ok: true, hwnd: "4242", index: 1 });
  assert.deepEqual(highlights, ["4242", "4242"]);
  assert.deepEqual(selected, [1]);
  assert.equal(renders.length, 2);
  assert.deepEqual(calls.map((call) => call.type), [
    "getVirtualDesktops",
    "getDesktopWindowHandles",
    "getDesktopWindowHandles",
    "switchVirtualDesktop",
    "restoreForegroundWindow",
  ]);
  assert.deepEqual(calls[3], { type: "switchVirtualDesktop", index: 1 });
  assert.deepEqual(calls[4], { type: "restoreForegroundWindow", hwnd: "4242" });

  const missingCalls = [];
  const missing = loadModule().create({
    nativeRequest: async (message) => {
      missingCalls.push({ ...message });
      if (message.type === "getVirtualDesktops") return { ok: true, desktopIds: ["desk-a"] };
      return { ok: true, hwnds: ["99"] };
    },
  });
  await assert.rejects(() => missing.activate("4242"), /실제 데스크톱 위치/);
  assert.equal(missingCalls.some((call) => call.type === "switchVirtualDesktop"), false);
  assert.equal(missingCalls.some((call) => call.type === "restoreForegroundWindow"), false);
  assert.throws(() => service.select("not-a-hwnd"), /BCT_NODE_HWND_INVALID/);

  const monitor = fs.readFileSync(monitorPath, "utf8");
  const css = fs.readFileSync(cssPath, "utf8");
  assert.match(monitor, /row\.addEventListener\("click"/);
  assert.match(monitor, /row\.addEventListener\("dblclick"/);
  assert.match(monitor, /resolveMonitorBctNodeHwnd/);
  assert.match(css, /monitor-bct-node-target-highlighted/);
  assert.match(css, /#ffd75a/);
  console.log(JSON.stringify({
    status: "PASS",
    exact_hwnd: result.hwnd,
    desktop_index: result.index,
    switch_before_foreground: true,
    missing_hwnd_has_no_side_effect: true,
    yellow_thumbnail_contract: true,
  }));
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
