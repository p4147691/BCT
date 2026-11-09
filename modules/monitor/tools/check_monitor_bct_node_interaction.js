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
const backgroundPath = path.join(root, "extension", "background.js");
const bootstrapPath = path.join(root, "extension", "google-bootstrap.js");
const nativeHostPath = path.join(root, "native", "src", "MonitorDesktopHost.cs");

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

  const preactivated = await service.focusExactTab(target);
  assert.equal(preactivated.status, "APPLIED");
  assert.deepEqual(focusedTabs, [target, target]);

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
  const background = fs.readFileSync(backgroundPath, "utf8");
  const bootstrap = fs.readFileSync(bootstrapPath, "utf8");
  const nativeHost = fs.readFileSync(nativeHostPath, "utf8");
  const restoreStart = nativeHost.indexOf("private static object RestoreForegroundWindow(");
  const restoreEnd = nativeHost.indexOf("\n    private static object GetCodexRuntimeStatus", restoreStart);
  const restore = nativeHost.slice(restoreStart, restoreEnd);
  assert.ok(restoreStart >= 0 && restoreEnd > restoreStart, "native foreground handler must be present");
  assert.match(restore, /IsIconic\(hWnd\)/,
    "node activation must detect a minimized browser window before foregrounding it");
  assert.match(restore, /ShowWindow\(hWnd, 9 \/\* SW_RESTORE \*\/\)/,
    "node activation must restore a minimized browser window");
  assert.match(restore, /GetForegroundWindow\(\) == hWnd/,
    "native success must prove the requested Chrome HWND is foreground");
  assert.match(restore, /\{ "ok", restored && foregroundMatched \}/,
    "native success must require both restore and foreground confirmation");
  assert.match(css, /\.monitor-bct-node-view-mode \{[^}]*color-scheme:dark;/,
    "node view selector must request a readable dark native popup");
  assert.match(css, /\.monitor-bct-node-view-mode option \{[^}]*background:#172535;[^}]*color:#eef6ff;/,
    "node view selector options must keep explicit contrast before hover");
  assert.match(monitor, /row\.addEventListener\("click"/);
  assert.match(monitor, /row\.addEventListener\("dblclick"/);
  assert.match(monitor, /focusExactTab\(tabTarget\)[\s\S]{0,300}resolveMonitorBctNodeHwnd\(node\)/,
    "node double-click must activate the exact Chrome tab before resolving its fresh HWND binding");
  assert.match(monitor, /const detail = monitorBctNodeDetail\(node, desktopPosition, nativeLocation\);\s*location\.textContent = detail\.text;/,
    "initial node-card render must use the complete compact detail contract");
  assert.match(monitor, /const detail = monitorBctNodeDetail\(node, index, location\);\s*position\.textContent = detail\.text;/,
    "location refresh must preserve surface, reasoning, age, and burden details");
  assert.doesNotMatch(monitor, /position\.textContent = monitorBctNodeLocationText\(node, index\)/,
    "location refresh must not collapse the detail line back to D# only");
  assert.match(monitor, /\.filter\(Boolean\)\.join\(" "\)/,
    "node detail fields must use wrappable spacing without punctuation separators");
  assert.match(css, /\.monitor-bct-node-location \{[^}]*word-spacing:3px;[^}]*white-space:normal;[^}]*max-height:2\.5em;/,
    "node detail must wrap to at most two readable lines instead of clipping the burden field");
  assert.match(monitor, /if \(!String\(node\?\.conversationKey \|\| ""\)\.trim\(\)\) return "New";/,
    "a blank conversation node must be labeled New");
  assert.match(monitor, /return kind === "WORK" \? "Work" : "Chat";/,
    "only positive Work evidence may override the stable Chat browser-surface fallback");
  assert.doesNotMatch(monitor, /\|\| "Chat\/Work";/,
    "node cards must never expose Chat\/Work as a final product kind");
  assert.match(monitor, /instant: "I"[\s\S]{0,260}low: "L"[\s\S]{0,260}medium: "M"[\s\S]{0,260}high: "H"[\s\S]{0,260}xhigh: "E"[\s\S]{0,260}pro: "P"/,
    "reasoning levels must use compact I/L/M/H/E/P card labels");
  assert.match(monitor, /return `관측 \$\{minutes\}분`;/,
    "observed age must remain in minutes at every age");
  assert.match(monitor, /desktopPosition >= 0 \? `D\$\{desktopPosition \+ 1\}` : "D\?"/,
    "unresolved location must be an explicit D? rather than an ambiguous underscore-like glyph");
  assert.match(monitor, /`\$\{locationText\}\$\{minimized \? " _" : ""\}`/,
    "a minimized node must use the compact underscore mark requested by the user");
  assert.match(monitor, /monitorBctDisplaySessionHwnd\(windowIdValue\);/,
    "display-only location must fall back to one unique Chrome window id while exact session identity converges");
  assert.match(monitor, /monitorBctDisplayWindowHwnd = new Map[\s\S]*monitorWorkers\?\.isConnected\) syncMonitorBctNodeLocationLabels\(\);/,
    "a refreshed display binding must repaint existing D? node-list labels without requiring another click");
  assert.match(monitor, /row\.addEventListener\("pointerdown", \(event\) => beginMonitorBctNodePointerDrag/);
  assert.match(monitor, /if \(monitorBctPointerDrag\) \{\s*monitorBctDeferredNodeRender = nodes;\s*return;/,
    "an RCC refresh must defer rather than cancel an active node drag");
  assert.match(monitor, /const deferred = monitorBctDeferredNodeRender;[\s\S]{0,220}if \(deferred && !monitorBctNodeReorderPending\) renderMonitorBctWindowNodes\(deferred\)/,
    "a canceled drag must repaint the newest deferred node snapshot");
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
  assert.match(monitor, /function installMonitorBctRoleLongPress\(/);
  assert.match(monitor, /drag\.roleArmed = drag\.row\?\.monitorBctPreviewRoleLongPress\?\.\(\) === true;/,
    "the unified node gesture must preview and arm a role long-press at 600ms");
  assert.match(monitor, /const commitRole = !drag\.active && drag\.roleArmed/,
    "only a stationary armed gesture may commit a role on release");
  assert.match(monitor, /row\.monitorBctCommitRoleLongPress = commit/,
    "role persistence must be invoked by the unified drag or hold controller");
  assert.match(monitor, /row\.classList\.add\("monitor-bct-role-save-pending"\)/,
    "a role write must be visibly pending without pretending the role was already saved");
  assert.match(monitor, /function applyMonitorBctPendingRoleProjections\(nodes, now = Date\.now\(\)\)/,
    "role saves must project by exact conversation while stale status replies are in flight");
  assert.match(monitor, /const nextNodes = applyMonitorBctPendingRoleProjections\(observedNodes\)/,
    "status refreshes must retain the exact pending role projection");
  assert.match(monitor, /actualScopeId === pending\.scopeId[\s\S]{0,220}monitorBctRoleSavePendingByKey\.delete\(key\)/,
    "the optimistic role projection must clear only after Core reports the same state");
  assert.match(monitor, /now >= pending\.expiresAt[\s\S]{0,100}monitorBctRoleSavePendingByKey\.delete\(key\)/,
    "a missing convergence must release the optimistic role projection after a bounded hold");
  assert.match(monitor, /monitorBctSelectedNodeKey = monitorBctNodeSelectionKey\(node\);[\s\S]{0,180}syncMonitorBctNodeTargetHighlight\(\)/,
    "starting a node drag must immediately select its source row");
  assert.match(monitor, /function monitorBctNodeRoleRank\(node\)[\s\S]{0,260}if \(tags\.includes\("supervisor"\)\) return 0;[\s\S]{0,80}if \(tags\.includes\("manager"\)\) return 1;/,
    "one shared role rank must define the pinned coordinator order");
  assert.match(monitor, /const roleDifference = monitorBctNodeRoleRank\(left\) - monitorBctNodeRoleRank\(right\);[\s\S]{0,80}if \(roleDifference\) return roleDifference;/,
    "supervisor and Manager cards must remain before manually ordered worker cards");
  assert.match(monitor, /const nextScopeName = role === "supervisor" \? "" : node\.scopeName/);
  assert.match(monitor, /if \(!monitorBctShell\?\.updateConversationScope \|\| \(!node\?\.conversationKey && !node\?\.dotKey && !node\?\.codexLocalReference\)\)/,
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
  assert.match(monitor, /monitorBctSelectedNodeKey = monitorBctNodeSelectionKey\(node\);[\s\S]{0,500}syncMonitorMinimizedNodeBadges\(monitorLastAiState\);[\s\S]{0,240}getMonitorBctNodeInteractionService\(\)\.select\(hwnd\)/,
    "selecting a node must immediately paint its minimized D# number before any window interaction");
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
  assert.match(monitor, /function scheduleMonitorChatNavigationRefresh\(message\)[\s\S]*?applyMonitorChatNavigationIdentity\(message, monitorLastAiState\);[\s\S]*?monitorChatNavigationPendingByTab\.set/,
    "a Chrome tab activation must paint current Monitor selection before slower state refreshes begin");
  assert.match(background, /chrome\.windows\.onFocusChanged\.addListener\(\(windowIdValue\) => \{[\s\S]{0,1200}chrome\.tabs\.query\(\{ windowId, active: true \}\)[\s\S]{0,850}publishMonitorChatNavigation\(tabId, tab\?\.url \|\| "", "window-focused", windowId, true\)/,
    "foregrounding an existing Chrome window must publish its already-active tab to Monitor");
  assert.match(background, /reasonText !== "tab-activated" && reasonText !== "window-focused"/,
    "a repeated window focus must not be suppressed just because the URL is unchanged");
  const foregroundStart = monitor.indexOf("function handleMonitorForegroundChangedEvent(event)");
  const foregroundEnd = monitor.indexOf("\nfunction removeMonitorV2Window", foregroundStart);
  const foregroundHandler = monitor.slice(foregroundStart, foregroundEnd);
  assert.match(foregroundHandler, /chrome\.tabs\.query\(\{ windowId, active:true \}\)/,
    "a BCT Chrome foreground event reads the exact active tab immediately");
  assert.match(foregroundHandler, /if\(bctNodes\.length\)[\s\S]*?return;[\s\S]*?applyMonitorWindowHighlight\(hwnd\)/,
    "a BCT Chrome foreground event bypasses generic HWND selection");
  assert.match(foregroundHandler, /if\(bctNodes\.length\)[\s\S]{0,1800}return;[\s\S]{0,800}if\(!visibleNode\)return;/,
    "a BCT foreground selection reaches the node list even before its thumbnail is rendered");
  const directClickStart = monitor.indexOf("function monitorApplyDirectUserClick(message, sender)");
  const directClickEnd = monitor.indexOf("\nfunction monitorApplyObservedChatTabSelection(", directClickStart);
  const directClickHandler = monitor.slice(directClickStart, directClickEnd);
  assert.match(directClickHandler, /monitorApplyObservedChatTabSelection\(message, sender\)/,
    "a real page click reuses exact observed-tab selection instead of generic HWND state");
  const observedTabStart = monitor.indexOf("function monitorApplyObservedChatTabSelection(message, sender)");
  const observedTabEnd = monitor.indexOf("\nfunction monitorApplyRoleMode(", observedTabStart);
  const observedTabHandler = monitor.slice(observedTabStart, observedTabEnd);
  assert.match(observedTabHandler, /Number\(node\?\.tabId\)===tabId && key && String\(node\?\.conversationKey\|\|""\)\.trim\(\)===key/,
    "a real ChatGPT page click resolves the exact sender tab and conversation node");
  assert.match(observedTabHandler, /nodes\.find\(\(node\)=>Number\(node\?\.tabId\)===tabId && !String\(node\?\.conversationKey\|\|""\)\.trim\(\)\)/,
    "an N? tab without a UUID remains selectable by its exact Chrome tab id");
  assert.doesNotMatch(observedTabHandler, /if \(!key \|\| !Number\.isInteger\(tabId\)/,
    "an N? tab is not rejected merely because its ChatGPT route has no UUID");
  assert.match(observedTabHandler, /monitorBctSelectedNodeKey=monitorBctNodeSelectionKey\(clickedNode\);[\s\S]{0,800}applyMonitorBctNodeHighlight\(displayHwnd\)/,
    "a real ChatGPT page click selects the BCT row and thumbnail rather than generic HWND state");
  assert.doesNotMatch(observedTabHandler, /if\(clickedNode\)[\s\S]{0,1000}applyMonitorWindowHighlight\(hwnd\)/,
    "the exact BCT click path must not clear its selection through generic HWND highlighting");
  assert.match(bootstrap, /const reportDirectTabSelection = \(\) => \{[\s\S]{0,500}type:"monitor-chat-tab-selected"/,
    "a selected ChatGPT page reports its exact conversation independently of Chrome tab events");
  assert.match(bootstrap, /visibilitychange[\s\S]{0,180}reportDirectTabSelection\(\)/,
    "switching to a ChatGPT tab reports selection as it becomes visible");
  assert.match(bootstrap, /const reportDirectTabSelection = \(\) => \{[\s\S]{0,240}const key = directConversationKey\(\);[\s\S]{0,240}conversationKey:key/,
    "the ChatGPT home/new-chat route reports its selected tab even with an empty conversation key");
  assert.match(monitor, /syncMonitorAllDesktopThumbnailNodeBadges\(\);/,
    "selection changes must reproject thumbnail number tokens immediately");
  assert.match(monitor, /renderMonitorBctWindowNodes\(monitorBctWindowNodesCache\);\s*syncMonitorBctNodeTargetHighlight\(\);/,
    "a regular Worker render must restore BCT-list ownership and exact row selection");
  assert.match(projection, /selectedNodeTabId/,
    "thumbnail selection must use the exact Chrome tabId, not a shared N? label");
  assert.match(css, /#ffd75a/);
  assert.match(css, /\.monitor-bct-node-row\.is-manager\s*\{[^}]*border-color:rgba\(255,255,255,\.12\)/,
    "Manager role color must stay in the fill while its resting border remains neutral");
  assert.match(css, /\.monitor-bct-node-row\.is-supervisor\s*\{[^}]*border-color:rgba\(255,255,255,\.12\)/,
    "Supervisor role color must stay in the fill while its resting border remains neutral");
  assert.match(css, /\.monitor-bct-node-row\.is-selected\s*\{[^}]*outline:2px solid rgba\(255,181,71,\.98\)!important/,
    "exact tab selection must use a separate strong outline rather than the role border");
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
  const managerRoleRule = css.match(/\.monitor-bct-node-row\.is-manager\s*\{([^}]+)\}/)?.[1] || "";
  const supervisorRoleRule = css.match(/\.monitor-bct-node-row\.is-supervisor\s*\{([^}]+)\}/)?.[1] || "";
  assert.match(managerRoleRule, /linear-gradient\(90deg,rgba\(196,124,8,\.58\),rgba\(238,169,20,\.34\)\)/,
    "Manager amber must carry the same saturated gradient weight as Supervisor blue");
  assert.match(managerRoleRule, /border-color:rgba\(255,255,255,\.12\)/,
    "Manager role border must stay neutral so exact selection remains unambiguous");
  assert.match(managerRoleRule, /box-shadow:inset 0 1px 0 rgba\(255,255,255,\.04\)/,
    "Manager role contrast must come from its fill rather than a selection-like glow");
  assert.match(supervisorRoleRule, /linear-gradient\(90deg/);
  assert.match(supervisorRoleRule, /border-color:rgba\(255,255,255,\.12\)/);
  assert.match(css, /\.monitor-bct-rename-dialog[^}]+max-height:calc\(100vh - 24px\)[^}]+overflow:auto/,
    "the node editor must scroll inside the viewport instead of clipping its confirmation buttons");
  assert.match(css, /\.monitor-bct-rename-actions[^}]+position:sticky[^}]+bottom:-13px/,
    "the node editor actions must remain visible while fields scroll");

  const pendingStart = monitor.indexOf("function applyMonitorBctPendingRoleProjections(");
  const holdStart = monitor.indexOf("function installMonitorBctRoleLongPress(");
  const holdEnd = monitor.indexOf("\nfunction getMonitorBctNodeInteractionService(", holdStart);
  assert.ok(pendingStart > 0 && holdStart > pendingStart && holdEnd > holdStart);
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
  const roleUpdates = [];
  const managerTransfers = [];
  const holdContext = {
    monitorBctSuppressedClickKey: "",
    monitorBctRoleSavePendingByKey: new Map(),
    monitorBctWindowNodesCache: [],
    monitorBctManagerStatuses: [],
    monitorBctNodeSelectionKey: (node) => node.conversationKey,
    monitorBctShell: {
      updateConversationScope: async (_node, values) => { roleUpdates.push(values); return { ok: true }; },
      transferManagerRole: async (node, manager) => {
        managerTransfers.push({ node, manager });
        return { project_id: node.scopeId, role_tags: [...node.roleTags, "Manager"], role_tags_sha256: "b".repeat(64) };
      },
    },
    refreshMonitorBctWindowNodes: async () => {},
    renderMonitorBctWindowNodes: () => {},
    syncMonitorAllDesktopThumbnailNodeBadges: () => {},
    recordMonitorBctRoleHistory: () => {},
    statusMessages: [],
    setMonitorStatus: (message) => { holdContext.statusMessages.push(message); },
    setTimeout() { return 1; },
    clearTimeout: () => {},
    globalThis: null,
    Array, String, Math, Promise, Date,
  };
  holdContext.globalThis = holdContext;
  vm.createContext(holdContext);
  vm.runInContext(monitor.slice(pendingStart, holdStart), holdContext);
  vm.runInContext(monitor.slice(holdStart, holdEnd), holdContext);
  holdContext.monitorBctRoleSavePendingByKey.set("conv-pending", {
    scopeId: "network-a", scopeName: "대화망 A", roleTags: ["Worker", "Manager"],
    roleTagsSha256: "", expiresAt: 2000,
  });
  const projected = holdContext.applyMonitorBctPendingRoleProjections([
    { conversationKey: "conv-pending", scopeId: "network-a", roleTags: ["Worker"] },
  ], 1000);
  assert.equal(projected[0].roleTags.includes("Manager"), true,
    "an older status reply must not flash the pending Manager role off");
  const converged = holdContext.applyMonitorBctPendingRoleProjections([
    { conversationKey: "conv-pending", scopeId: "network-a", roleTags: ["Worker", "Manager"] },
  ], 1100);
  assert.equal(converged[0].roleTags.includes("Manager"), true);
  assert.equal(holdContext.monitorBctRoleSavePendingByKey.has("conv-pending"), false,
    "the pending projection clears when Core reports the same exact role state");
  const rowOn = managerRow();
  const baseNode = { conversationKey: "conv-1", nodeLabel: "N33", title: "대화", scopeName: "대화망 A", roleTags: ["Worker"] };
  holdContext.monitorBctWindowNodesCache = [baseNode];
  holdContext.installMonitorBctRoleLongPress(rowOn, baseNode);
  assert.equal(rowOn.listeners.size, 0, "role persistence must not install a competing pointer handler");
  assert.equal(rowOn.monitorBctPreviewRoleLongPress(), true);
  assert.equal(rowOn.classes.has("is-manager"), true, "the role color appears at the hold threshold");
  rowOn.monitorBctCancelRoleLongPressPreview();
  assert.equal(rowOn.classes.has("is-manager"), false, "a canceled hold restores the previous role color");
  rowOn.monitorBctPreviewRoleLongPress();
  rowOn.monitorBctCommitRoleLongPress();
  assert.equal(rowOn.classes.has("is-manager"), true, "a released hold paints its committed role immediately");
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(Array.from(roleUpdates[0].roleTags), ["Worker", "Manager"]);
  assert.equal(holdContext.monitorBctWindowNodesCache[0]?.roleTags?.includes?.("Manager"), true,
    "the persisted reply updates the visible cache before the full status refresh finishes");
  const rowOff = managerRow();
  holdContext.installMonitorBctRoleLongPress(rowOff, { ...baseNode, roleTags: ["Worker", "Manager"] });
  rowOff.monitorBctCommitRoleLongPress();
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(Array.from(roleUpdates[1].roleTags), ["Worker"]);
  assert.equal(rowOff.classes.has("is-manager"), false);

  const supervisorOn = managerRow();
  holdContext.installMonitorBctRoleLongPress(supervisorOn, { ...baseNode, scopeName: "", roleTags: ["Worker"] });
  supervisorOn.monitorBctCommitRoleLongPress();
  assert.equal(supervisorOn.classes.has("is-supervisor"), true);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(roleUpdates[2].scopeName, "");
  assert.deepEqual(Array.from(roleUpdates[2].roleTags), ["Worker", "supervisor"]);

  const supervisorOff = managerRow();
  holdContext.installMonitorBctRoleLongPress(supervisorOff, { ...baseNode, scopeName: "", roleTags: ["Worker", "supervisor"] });
  supervisorOff.monitorBctCommitRoleLongPress();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(roleUpdates[3].scopeName, "");
  assert.deepEqual(Array.from(roleUpdates[3].roleTags), ["Worker"]);
  assert.equal(supervisorOff.classes.has("is-supervisor"), false);

  holdContext.monitorBctWindowNodesCache = [{
    conversationKey: "conv-supervisor", nodeLabel: "N97", scopeName: "", roleTags: ["supervisor"],
  }];
  const secondSupervisor = managerRow();
  holdContext.installMonitorBctRoleLongPress(secondSupervisor, { ...baseNode, conversationKey: "conv-2", scopeName: "", roleTags: ["Worker"] });
  secondSupervisor.monitorBctCommitRoleLongPress();
  await Promise.resolve();
  assert.equal(roleUpdates.length, 4, "a second global supervisor must not be saved");
  assert.match(holdContext.statusMessages.at(-1), /감독관은 하나만/);

  holdContext.monitorBctManagerStatuses = [{
    scopeId: "scope-a", status: "NOT_OPEN", managerConversationKey: "closed-manager", managerNodeLabel: "N98",
  }];
  const successorManager = managerRow();
  holdContext.installMonitorBctRoleLongPress(successorManager, {
    ...baseNode, conversationKey: "conv-3", scopeId: "scope-a", scopeName: "대화망 A", roleTags: ["Worker"],
    roleTagsSha256: "a".repeat(64),
  });
  assert.equal(successorManager.monitorBctPreviewRoleLongPress(), true,
    "a user's explicit hold may preview succession from a closed Manager");
  successorManager.monitorBctCommitRoleLongPress();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(roleUpdates.length, 4, "explicit succession must not create a second Manager through set-node-info");
  assert.equal(managerTransfers.length, 1, "explicit succession uses the atomic Manager transfer path");
  assert.equal(managerTransfers[0].manager.managerNodeLabel, "N98");
  assert.match(holdContext.statusMessages.at(-1), /역할을 넘겼습니다/);

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

  const historyStart = monitor.indexOf("function updateMonitorBctRoleHistoryUi(");
  const historyEnd = monitor.indexOf("monitorBctRoleUndo?.addEventListener", historyStart);
  assert.ok(historyStart > 0 && historyEnd > historyStart);
  const historyWrites = [];
  const historyContext = {
    monitorBctRoleUndo: { disabled: true, addEventListener() {} }, monitorBctRoleRedo: { disabled: true, addEventListener() {} },
    monitorBctRoleUndoStack: [], monitorBctRoleRedoStack: [],
    monitorBctRoleHistoryBusy: false, MONITOR_BCT_ROLE_HISTORY_LIMIT: 30,
    monitorBctWindowNodesCache: [{ conversationKey: "conv-1", scopeId: "scope-a", scopeName: "A", title: "Node", roleTags: ["Worker", "Manager"], roleTagsSha256: "a".repeat(64) }],
    monitorBctShell: { updateConversationScope: async (_node, values) => {
      historyWrites.push(values);
      historyContext.monitorBctWindowNodesCache[0].roleTags = [...values.roleTags];
      return {};
    } },
    refreshMonitorBctWindowNodes: async () => {}, setMonitorStatus: () => {},
    Object, Array, String,
  };
  vm.createContext(historyContext);
  vm.runInContext(monitor.slice(historyStart, historyEnd), historyContext);
  historyContext.recordMonitorBctRoleHistory({
    conversationKey: "conv-1", scopeId: "scope-a",
    beforeRoleTags: ["Worker"], afterRoleTags: ["Worker", "Manager"],
  });
  assert.equal(historyContext.monitorBctRoleUndo.disabled, false);
  await historyContext.applyMonitorBctRoleHistory("undo");
  assert.deepEqual(Array.from(historyWrites[0].roleTags), ["Worker"]);
  assert.equal(historyContext.monitorBctRoleRedo.disabled, false);
  await historyContext.applyMonitorBctRoleHistory("redo");
  assert.deepEqual(Array.from(historyWrites[1].roleTags), ["Worker", "Manager"]);
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
    role_history_undo_redo: true,
    title_is_not_drop_target: true,
    wrapped_row_append_uses_last_node_edge: true,
  }));
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
