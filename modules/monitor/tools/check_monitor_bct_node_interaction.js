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
  const focusedTabs = [];
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
    focusBrowserTab: async (target) => {
      focusedTabs.push({ ...target });
      return { ok: true, status: "APPLIED", schema: "monitor.browser.tab-focus.receipt.v1" };
    },
  });
  const target = { tabId: 17, windowId: 33, conversationKey: "6ad733b6-95d4-83ee-b4ba-49a671229d77" };
  const result = await service.activate("4242", target);
  assert.equal(result.ok, true);
  assert.equal(result.hwnd, "4242");
  assert.equal(result.index, 1);
  assert.equal(result.tabReceipt.status, "APPLIED");
  assert.deepEqual(focusedTabs, [target]);
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

  const focusFailure = loadModule().create({
    nativeRequest,
    focusBrowserTab: async () => ({ ok: false, status: "NOT_APPLIED", error: "IDENTITY_MISMATCH" }),
  });
  await assert.rejects(() => focusFailure.activate("4242", target), /IDENTITY_MISMATCH/);

  const monitor = fs.readFileSync(monitorPath, "utf8");
  const css = fs.readFileSync(cssPath, "utf8");
  assert.match(monitor, /row\.addEventListener\("click"/);
  assert.match(monitor, /row\.addEventListener\("dblclick"/);
  assert.match(monitor, /resolveMonitorBctNodeHwnd/);
  assert.match(monitor, /monitorBctSelectedNodeKey = monitorBctNodeSelectionKey\(node\)/);
  assert.match(css, /monitor-bct-node-target-highlighted/);
  assert.match(css, /#ffd75a/);

  const selectionStart = monitor.indexOf("function syncMonitorBctNodeTargetHighlight(");
  const selectionEnd = monitor.indexOf("\nfunction applyMonitorBctNodeHighlight(", selectionStart);
  assert.ok(selectionStart > 0 && selectionEnd > selectionStart);
  function row(tabId) {
    const classes = new Set();
    return {
      dataset: { instanceId: "rcc-1", sessionId: "session-1", windowId: "100", tabId: String(tabId) },
      classList: { toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); } },
      setAttribute(name, value) { this[name] = value; },
      classes,
    };
  }
  const first = row(11), second = row(12), third = row(13);
  const selectionContext = {
    monitorBctNodeHighlightedHwnd: "4242",
    monitorBctSelectedNodeKey: "rcc-1:session-1:100:12",
    monitorWorkers: { querySelectorAll: () => [first, second, third] },
    document: { querySelectorAll: () => [] },
    String, Boolean,
  };
  vm.createContext(selectionContext);
  vm.runInContext(monitor.slice(selectionStart, selectionEnd), selectionContext);
  selectionContext.syncMonitorBctNodeTargetHighlight();
  assert.equal(first.classes.has("is-selected"), false);
  assert.equal(second.classes.has("is-selected"), true);
  assert.equal(third.classes.has("is-selected"), false);
  console.log(JSON.stringify({
    status: "PASS",
    exact_hwnd: result.hwnd,
    desktop_index: result.index,
    switch_before_foreground: true,
    missing_hwnd_has_no_side_effect: true,
    yellow_thumbnail_contract: true,
    exact_node_card_selection: true,
    exact_tab_focus: true,
  }));
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
