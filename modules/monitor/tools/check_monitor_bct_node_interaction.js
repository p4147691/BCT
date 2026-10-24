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
  assert.match(monitor, /row\.addEventListener\("pointerdown", \(event\) => beginMonitorBctNodePointerDrag/);
  assert.match(monitor, /function updateMonitorBctNodePointerDrag/);
  assert.match(monitor, /function monitorBctNodeDropAt/);
  assert.match(monitor, /groupList\.className = "monitor-bct-node-list"/);
  assert.doesNotMatch(monitor, /groupHeader\.addEventListener\("drop"/);
  assert.match(monitor, /commitMonitorBctNodeDrop/);
  assert.match(monitor, /monitorBctShell\.reorderConversations/);
  assert.match(monitor, /tags\.filter\(\(tag\) => tag !== "Manager"\)/);
  assert.match(monitor, /row\.classList\.toggle\("is-manager", !hadManager\)/);
  assert.match(monitor, /monitorBctPointInsideScopeHeading/);
  assert.match(monitor, /monitorBctNodeInsertionAt/);
  assert.match(monitor, /row\.setPointerCapture\(event\.pointerId\)/);
  assert.doesNotMatch(monitor, /monitor-bct-node-list-end/);
  assert.match(monitor, /resolveMonitorBctNodeHwnd/);
  assert.match(monitor, /monitorBctSelectedNodeKey = monitorBctNodeSelectionKey\(node\)/);
  assert.match(css, /monitor-bct-node-target-highlighted/);
  assert.match(css, /#ffd75a/);
  assert.match(css, /monitor-bct-drop-before/);
  assert.doesNotMatch(css, /monitor-bct-node-list-end/);
  assert.match(css, /monitor-bct-node-drag-active \.monitor-bct-scope-heading \{ pointer-events:none!important; \}/);
  assert.match(css, /monitor-bct-node-drag-active/);
  assert.match(css, /monitor-bct-node-drag-ghost/);
  assert.match(css, /background:rgba\(12,24,38,\.68\)/,
    'BCT drag ghost must remain translucent enough to reveal the insertion line');
  assert.doesNotMatch(css, /monitor-bct-node-drag-ghost[\s\S]{0,240}background:rgba\(12,24,38,\.92\)/);
  const selectedRule = css.match(/\.monitor-bct-node-row\.is-selected\s*\{([^}]+)\}/)?.[1] || "";
  assert.doesNotMatch(selectedRule, /background:/);

  const dropStart = monitor.indexOf("function monitorBctPointInsideScopeHeading(");
  const dropEnd = monitor.indexOf("\nfunction updateMonitorBctNodePointerDrag(", dropStart);
  assert.ok(dropStart > 0 && dropEnd > dropStart);
  function dropRow(key, left, top) {
    const classes = new Set();
    return {
      hidden: false,
      dataset: { conversationKey: key },
      getBoundingClientRect: () => ({ left, right: left + 80, top, bottom: top + 30, width: 80, height: 30 }),
      classList: { add: (...names) => names.forEach((name) => classes.add(name)) },
      classes,
    };
  }
  const dropRows = [
    dropRow("n1", 0, 40),
    dropRow("n2", 90, 40),
    dropRow("n3", 180, 40),
    dropRow("n4", 0, 80),
  ];
  const listClasses = new Set();
  const list = {
    dataset: { scopeId: "scope-a" },
    hidden: false,
    getBoundingClientRect: () => ({ left: 0, right: 300, top: 40, bottom: 120, width: 300, height: 80 }),
    querySelectorAll: () => dropRows,
    classList: { add: (...names) => names.forEach((name) => listClasses.add(name)) },
  };
  const dropContext = {
    monitorWorkers: {
      contains: (candidate) => candidate === list,
      querySelectorAll: (selector) => selector === ".monitor-bct-node-list" ? [list] : [{ getBoundingClientRect: () => ({ left: 0, right: 300, top: 0, bottom: 30 }) }],
    },
    document: { elementFromPoint: () => ({ closest: (selector) => selector === ".monitor-bct-node-list" ? list : null }) },
    String, Array,
  };
  vm.createContext(dropContext);
  vm.runInContext(monitor.slice(dropStart, dropEnd), dropContext);
  assert.equal(dropContext.monitorBctNodeDropAt(100, 15, "dragged"), null, "scope heading is never a drop target");
  dropContext.monitorWorkers.querySelectorAll = (selector) => selector === ".monitor-bct-node-list" ? [list] : [];
  const appendDrop = dropContext.monitorBctNodeDropAt(290, 92, "dragged");
  assert.deepEqual(JSON.parse(JSON.stringify(appendDrop)), {
    scopeId: "scope-a",
    targetConversationKey: "n4",
    position: "after",
  });
  assert.equal(dropRows[3].classes.has("monitor-bct-drop-after"), true);
  assert.equal(listClasses.has("monitor-bct-node-list-target"), true);

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
    manager_long_press_toggle: true,
    title_is_not_drop_target: true,
    wrapped_row_append_uses_last_node_edge: true,
  }));
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
