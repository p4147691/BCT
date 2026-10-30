"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../extension/monitor-bct-thumbnail-projection.js"), "utf8",
);
const monitorSource = fs.readFileSync(path.join(__dirname, "../extension/monitor.js"), "utf8");
const backgroundSource = fs.readFileSync(path.join(__dirname, "../extension/background.js"), "utf8");
assert.match(monitorSource,
  /function syncMonitorThumbnailTabBadges\([\s\S]*MonitorBctThumbnailProjection[\s\S]*return diagnostics;/,
  "the active thumbnail path must delegate to the isolated projection renderer");
assert.match(monitorSource,
  /items\.filter\(\(item\) => monitorWindowCanRefreshPixels\(item\) && !monitorWindowUsesFrozenCapture\(item\)\)/,
  "the frozen Monitor self frame must never enter recurring thumbnail WGC capture");
assert.match(monitorSource, /await ensureMonitorOwnFrozenSnapshot\(\)/,
  "the host desktop frame must wait for the bounded one-shot Monitor self capture");
assert.match(monitorSource, /includeMonitorWindows:\s*true/,
  "the authoritative Native HWND snapshot must include the exact Monitor window");
assert.match(monitorSource,
  /itemHwnd === hostHwnd && monitorIsOwnWindowTitle\(item\?\.title\)/,
  "the frozen-frame exception must require the exact registered Monitor HWND");
assert.match(monitorSource,
  /const currentWindowRows = handlesConfirmed\s*\? \[\.\.\.handleByHwnd\.values\(\), \.\.\.monitorPopupWindows\]\s*:\s*windows;/,
  "a successful Native snapshot must retain the exact frozen Monitor self row");
assert.match(monitorSource,
  /scheduleMonitorChatNavigationRefresh\(message\)[\s\S]*await refreshMonitorBctWindowNodes\(\);[\s\S]*syncMonitorAllDesktopThumbnailNodeBadges\(\);/,
  "Chrome navigation must refresh RCC window membership and node badges without Monitor focus");
const refreshOwner = fs.readFileSync(path.join(__dirname, "../extension/monitor-node-panel-refresh.js"), "utf8");
assert.match(monitorSource, /MonitorNodePanelRefresh[.]create/,
  "NodePanel refresh must route through its independent lifecycle owner");
assert.match(refreshOwner, /if\(busy\) \{ pending=true; return false; \}/,
  "a navigation refresh arriving during an in-flight RCC read must be coalesced, not lost");
const monitorCss = fs.readFileSync(path.join(__dirname, "../extension/monitor.css"), "utf8");
assert.match(monitorCss, /\.monitor-thumbnail-tab-badge\s*\{[^}]*overflow-wrap:normal[^}]*word-break:normal/s,
  "a thumbnail window node label may wrap only at its natural separators, never through a node number");
assert.match(backgroundSource, /chrome\.tabs\.onAttached\.addListener/,
  "moving a tab into another Chrome window must publish a refresh event");
assert.match(backgroundSource, /chrome\.tabs\.onDetached\.addListener/,
  "the old Chrome window must refresh when a tab leaves it");
assert.match(backgroundSource, /chrome\.tabs\.onMoved\.addListener/,
  "tab-order changes must refresh node-number order");
assert.match(backgroundSource, /chrome\.tabs\.onCreated\.addListener/,
  "a UUID-less new tab must enter the observed thumbnail order");
assert.match(backgroundSource, /chrome\.tabs\.query\(\{ windowId \}\)/,
  "a tab-order event must carry the complete current Chrome ordering, not only the active tab");
assert.match(monitorSource, /function applyMonitorBrowserVisualTabSnapshot[\s\S]*function monitorBrowserVisualTabsForWindow/,
  "Monitor must retain the observed tab order independently of a later Core refresh");

function node(className = "") {
  const result = {
    className,
    dataset: {},
    style: {},
    children: [],
    parentElement: null,
    hidden: false,
    classList: {
      owner: null,
      toggle(name, enabled) {
        const names = new Set(String(this.owner.className || "").split(/\s+/).filter(Boolean));
        if (enabled) names.add(name); else names.delete(name);
        this.owner.className = [...names].join(" ");
      },
    },
    append(child) {
      if (child.parentElement) {
        child.parentElement.children = child.parentElement.children.filter((item) => item !== child);
      }
      child.parentElement = this;
      this.children.push(child);
    },
    replaceChildren(...children) {
      for (const child of this.children) child.parentElement = null;
      this.children = children;
      for (const child of children) child.parentElement = this;
    },
    remove() {
      if (!this.parentElement) return;
      this.parentElement.children = this.parentElement.children.filter((item) => item !== this);
      this.parentElement = null;
    },
    setAttribute(name, value) { this[name] = String(value); },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) {
      const classes = selector.split(",").map((value) => value.trim().replace(/^\./, "").replace(/\[.*$/, ""));
      const found = [];
      const visit = (item) => {
        for (const child of item.children || []) {
          const names = String(child.className || "").split(/\s+/);
          if (classes.some((name) => names.includes(name))) found.push(child);
          visit(child);
        }
      };
      visit(this);
      return found;
    },
  };
  result.classList.owner = result;
  return result;
}

const context = {
  globalThis: null,
  document: { createElement: () => node() },
  String, Number, Boolean, Set, Object, Array,
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context);

const visual = node("monitor-desktop-thumb-visual");
visual.dataset.desktopId = "desk-a";

function image(hwnd, z, left = "0%") {
  const result = node("monitor-desktop-thumb-window");
  result.dataset.hwnd = String(hwnd);
  result.dataset.nativeZIndex = String(z);
  Object.assign(result.style, {
    left,
    top: "0%",
    width: "50%",
    height: "100%",
    zIndex: String(z),
  });
  visual.append(result);
  return result;
}

const rear = image("500", 9000, "0%");
const front = image("600", 9800, "25%");
const nodeNumbers = new Map([
  ["500", [33, 35, "?", 45, 35]],
  ["600", [7, 8, 9, 10, 11, 12, 13, 14]],
]);

const render = () => context.MonitorBctThumbnailProjection.render({
  container: visual,
  state: null,
  highlightedHwnd: "500",
  numbersForHwnd: (hwnd) => nodeNumbers.get(hwnd) || [],
});

const first = render();
assert.deepEqual(
  { status: first.status, candidates: first.candidates, matched: first.matched, rendered: first.rendered },
  { status: "RENDERED", candidates: 2, matched: 2, rendered: 2 },
);
const layer = visual.querySelector(".monitor-thumbnail-node-overlay");
assert.ok(layer, "one dedicated node projection root must be created");
assert.equal(layer.querySelectorAll(".monitor-thumbnail-node-window").length, 2);
const overlays = new Map(layer.querySelectorAll(".monitor-thumbnail-node-window")
  .map((item) => [item.dataset.hwnd, item]));
assert.equal(overlays.get("500").style.zIndex, rear.style.zIndex,
  "a rear label must share the rear window z-order");
assert.equal(overlays.get("600").style.zIndex, front.style.zIndex,
  "a front label must share the front window z-order");
assert.match(overlays.get("500").className, /monitor-bct-node-target-highlighted/);
function badgeText(badge) {
  return (badge.children || []).map((part) => part.textContent).join("") || badge.textContent;
}
assert.equal(badgeText(overlays.get("500").querySelector(".monitor-thumbnail-tab-badge")), "33/35/?/45");
assert.equal(
  badgeText(overlays.get("600").querySelector(".monitor-thumbnail-tab-badge")),
  "7/8/9/10/11/12/13/14",
  "all tabs must remain visible; wrapping belongs to CSS and no +n abbreviation is allowed",
);
assert.deepEqual(overlays.get("500").querySelector(".monitor-thumbnail-tab-badge").children.map((part) => part.textContent), ["33", "/", "35", "/", "?", "/", "45"], "separators, and numeric tokens must remain individually addressable so only a selected number can enlarge");
assert.equal(layer.querySelector(".monitor-thumbnail-z-rail"), null,
  "collision rails must not exist in the simplified projection");
assert.equal(layer.querySelector(".monitor-thumbnail-node-chip"), null,
  "per-node chips and state icons are outside the static node-label layer");
assert.equal(first.repositioned, 0);
assert.equal(first.unresolvedCollisions, 0);

const unknownSelection = context.MonitorBctThumbnailProjection.render({
  container: visual,
  state: null,
  selectedNodeHwnd: "500",
  selectedNodeToken: "?",
  selectedNodeTabId: 202,
  numbersForHwnd: (hwnd) => hwnd === "500"
    ? [{ token: "?", tabId: 101 }, { token: "?", tabId: 202 }]
    : [],
});
assert.equal(unknownSelection.rendered, 1);
const unknownParts = layer.querySelector(".monitor-thumbnail-tab-badge").children
  .filter((part) => String(part.className || "").includes("monitor-thumbnail-tab-token"));
assert.equal(unknownParts.length, 2, "two UUID-less tabs must remain distinct visible tokens");
assert.deepEqual(unknownParts.map((part) => String(part.className || "").includes("is-selected")), [false, true],
  "selecting one UUID-less tab must highlight only its exact Chrome tabId");

const knownSelection = context.MonitorBctThumbnailProjection.render({
  container: visual,
  state: null,
  selectedNodeHwnd: "500",
  selectedNodeToken: "33",
  numbersForHwnd: (hwnd) => hwnd === "500" ? [33, 35] : [],
});
assert.equal(knownSelection.rendered, 1);
const knownParts = layer.querySelector(".monitor-thumbnail-tab-badge").children
  .filter((part) => String(part.className || "").includes("monitor-thumbnail-tab-token"));
assert.deepEqual(knownParts.map((part) => String(part.className || "").includes("is-selected")), [true, false],
  "known node selection remains exact when no tabId was supplied");

render();
assert.equal(visual.querySelectorAll(".monitor-thumbnail-node-overlay").length, 1);
assert.equal(layer.querySelectorAll(".monitor-thumbnail-tab-badge").length, 2,
  "re-render must replace, not accumulate, node labels");

rear.hidden = true;
const hidden = render();
assert.equal(hidden.rendered, 1);
assert.equal(hidden.skipped.hidden, 1,
  "a hidden physical image must not leave a floating node label");

rear.hidden = false;
rear.remove();
const removed = render();
assert.equal(removed.candidates, 1);
assert.equal(removed.rendered, 1,
  "Native geometry without a rendered image must not synthesize a label");

console.log("PASS: simple top-left number labels keep tab order, wrap without truncation, and share physical HWND z-order");
