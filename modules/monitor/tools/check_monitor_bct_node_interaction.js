"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const modulePath = path.join(root, "extension", "monitor-bct-node-interaction.js");
const monitorPath = path.join(root, "extension", "monitor.js");
const cssPath = path.join(root, "extension", "monitor.css");
const projectionPath = path.join(root, "extension", "monitor-bct-thumbnail-projection.js");

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
  const projection = fs.readFileSync(projectionPath, "utf8");
  assert.match(monitor, /row\.addEventListener\("click"/);
  assert.match(monitor, /row\.addEventListener\("dblclick"/);
  assert.match(monitor, /row\.addEventListener\("pointerdown", \(event\) => beginMonitorBctNodePointerDrag/);
  assert.match(monitor, /function updateMonitorBctNodePointerDrag/);
  assert.match(monitor, /function monitorBctNodeDropAt/);
  assert.match(monitor, /groupList\.className = "monitor-bct-node-list"/);
  assert.match(monitor, /groups\.has\("__unassigned__"\)/,
    "an empty unassigned group must remain available as a drop destination");
  assert.match(monitor, /monitor-bct-node-drop-empty/,
    "empty unassigned drop surface must be rendered inside its list");
  assert.match(monitor, /const scopeName = String\(list\.dataset\.scopeName \|\| ""\)\.trim\(\)/,
    "drop resolution must carry the destination network name");
  assert.doesNotMatch(monitor, /groupHeader\.addEventListener\("drop"/);
  assert.match(monitor, /commitMonitorBctNodeDrop/);
  assert.match(monitor, /monitorBctShell\.reorderConversations/);
  assert.match(monitor, /tags\.filter\(\(tag\) => tag !== "Manager"\)/);
  assert.match(monitor, /row\.classList\.toggle\("is-manager", !hadManager\)/);
  assert.match(monitor, /if \(!monitorBctShell\?\.updateConversationScope \|\| !node\?\.conversationKey\)/,
    "conversation metadata editor must be available independently of exact tab rename identity");
  assert.match(monitor, /titleField\.control\.disabled = !canRenameTitle/,
    "only exact ChatGPT title rename is disabled when tab identity is incomplete");
  assert.match(monitor, /대화망과 역할은 변경할 수 있습니다/,
    "the editor explains that persistent network and role metadata remain editable");
  assert.match(monitor, /monitorBctPointInsideScopeHeading/);
  assert.match(monitor, /monitorBctNodeInsertionAt/);
  assert.match(monitor, /row\.setPointerCapture\(event\.pointerId\)/);
  assert.doesNotMatch(monitor, /monitor-bct-node-list-end/);
  assert.match(monitor, /resolveMonitorBctNodeHwnd/);
  assert.match(monitor, /monitorBctSelectedNodeKey = monitorBctNodeSelectionKey\(node\)/);
  assert.match(monitor, /function applyMonitorBctNodeHighlight\(hwnd\)[\s\S]{0,700}applyMonitorWindowHighlight\("", \{ preserve: true, remote: true \}\)[\s\S]{0,240}publishMonitorSharedSelection\(\)/,
    "BCT node selection must clear generic HWND selection instead of decorating the real Chrome window");
  assert.doesNotMatch(monitor, /function applyMonitorBctNodeHighlight\(hwnd\)[\s\S]{0,400}applyMonitorWindowHighlight\(hwnd/,
    "BCT node selection must never forward its HWND to the generic window-selection path");
  assert.match(css, /monitor-bct-node-target-highlighted/);
  assert.doesNotMatch(css, /\.monitor-bct-node-row\.is-selected \.monitor-bct-node-number/,
    "the node-list number remains neutral; selection belongs only in the thumbnail");
  assert.match(css, /\.monitor-thumbnail-tab-token\.is-selected/,
    "thumbnail selection must be token-level, not a full badge fill");
  assert.match(css, /\.monitor-thumbnail-tab-prefix,.monitor-thumbnail-tab-separator/,
    "the N prefix and slash separators must remain at baseline size");
  assert.match(projection, /monitor-thumbnail-tab-separator/,
    "the projection must render slash separators separately from number tokens");
  assert.doesNotMatch(css, /monitor-bct-node-target-highlighted \.monitor-thumbnail-tab-badge \{[^}]*background:#ffd75a/,
    "a selected tab must not paint its thumbnail badge background yellow");
  assert.match(monitor, /A tab without a conversation UUID is still a real observed `N\?` entry/,
    "tab activation must retain an unregistered N? entry");
  assert.match(monitor, /Number\(node\?\.windowId\) === windowId && Number\(node\?\.tabId\) === tabId/,
    "tab activation must select by exact Chrome window/tab identity");
  assert.match(monitor, /const displayHwnd = monitorDisplayHwndForBrowserWindowId\([\s\S]*?if \(displayHwnd\) applyMonitorBctNodeHighlight\(displayHwnd\)/,
    "an actual Chrome tab activation must also project the exact browser-window perimeter into Monitor");
  assert.match(monitor, /refreshMonitorBctDisplayWindowHwnd\(\);\s*\/\/ The first pass may happen[\s\S]{0,380}applyMonitorChatNavigationIdentity\(item, monitorLastAiState\)/,
    "an actual Chrome tab activation is re-projected after the current HWND index refresh");
  assert.match(monitor, /function handleMonitorForegroundChangedEvent\(event\)[\s\S]{0,1100}if\(bctNodes\.length\)[\s\S]{0,700}return;[\s\S]{0,120}applyMonitorWindowHighlight\(hwnd\)/,
    "a BCT Chrome foreground event bypasses generic HWND selection and waits for its exact tab event");
  assert.match(monitor, /syncMonitorAllDesktopThumbnailNodeBadges\(\);/,
    "selection changes must reproject thumbnail number tokens immediately");
  assert.match(monitor, /renderMonitorBctWindowNodes\(monitorBctWindowNodesCache\);\s*syncMonitorBctNodeTargetHighlight\(\);/,
    "a regular Worker render must restore BCT-list ownership and exact row selection");
  assert.match(projection, /selectedNodeTabId/,
    "thumbnail selection must use the exact Chrome tabId, not a shared N? label");
  assert.match(css, /#ffd75a/);
  assert.match(css, /monitor-bct-node-target-highlighted[\s\S]{0,480}outline:3px solid rgba\(255,181,71,\.98\)!important/,
    "the exact selected browser window retains a visible thumbnail perimeter");
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

  const holdStart = monitor.indexOf("function installMonitorBctManagerLongPress(");
  const holdEnd = monitor.indexOf("\nfunction getMonitorBctNodeInteractionService(", holdStart);
  assert.ok(holdStart > 0 && holdEnd > holdStart);
  function managerRow() {
    const listeners = new Map();
    const classes = new Set();
    return {
      listeners,
      classes,
      addEventListener(type, listener) { listeners.set(type, listener); },
      classList: {
        add(name) { classes.add(name); },
        remove(name) { classes.delete(name); },
        toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
      },
    };
  }
  const holdTimers = [];
  const managerUpdates = [];
  const holdContext = {
    monitorBctSuppressedClickKey: "",
    monitorBctNodeSelectionKey: (node) => node.conversationKey,
    monitorBctShell: {
      updateConversationScope: async (_node, values) => { managerUpdates.push(values); return { ok: true }; },
    },
    refreshMonitorBctWindowNodes: async () => {},
    setMonitorStatus: () => {},
    setTimeout(callback, delay) { holdTimers.push({ callback, delay }); return holdTimers.length; },
    clearTimeout: () => {},
    globalThis: null,
    Array, String, Math, Promise,
  };
  holdContext.globalThis = holdContext;
  vm.createContext(holdContext);
  vm.runInContext(monitor.slice(holdStart, holdEnd), holdContext);
  const rowOn = managerRow();
  const baseNode = { conversationKey: "conv-1", nodeLabel: "N33", title: "대화", scopeName: "대화망 A", roleTags: ["Worker"] };
  holdContext.installMonitorBctManagerLongPress(rowOn, baseNode);
  rowOn.listeners.get("pointerdown")({ button: 0, clientX: 10, clientY: 10, target: { closest: () => null } });
  assert.equal(holdTimers[0].delay, 600);
  holdTimers[0].callback();
  await Promise.resolve();
  assert.deepEqual(Array.from(managerUpdates[0].roleTags), ["Worker", "Manager"]);
  assert.equal(rowOn.classes.has("is-manager"), true);
  const rowOff = managerRow();
  holdContext.installMonitorBctManagerLongPress(rowOff, { ...baseNode, roleTags: ["Worker", "Manager"] });
  rowOff.listeners.get("pointerdown")({ button: 0, clientX: 20, clientY: 20, target: { closest: () => null } });
  holdTimers.at(-1).callback();
  await Promise.resolve();
  assert.deepEqual(Array.from(managerUpdates[1].roleTags), ["Worker"]);
  assert.equal(rowOff.classes.has("is-manager"), false);

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
    dataset: { scopeId: "scope-a", scopeName: "Scope A" },
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
    scopeName: "Scope A",
    targetConversationKey: "n4",
    position: "after",
  });
  assert.equal(dropRows[3].classes.has("monitor-bct-drop-after"), true);
  assert.equal(listClasses.has("monitor-bct-node-list-target"), true);
  list.querySelectorAll = () => [];
  const emptyDrop = dropContext.monitorBctNodeDropAt(100, 92, "dragged");
  assert.deepEqual(JSON.parse(JSON.stringify(emptyDrop)), {
    scopeId: "scope-a",
    scopeName: "Scope A",
    targetConversationKey: "",
    position: "append",
  }, "an empty scope list remains a valid append destination");

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
