"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../extension/monitor-bct-thumbnail-projection.js"), "utf8",
);
const monitorSource = fs.readFileSync(path.join(__dirname, "../extension/monitor.js"), "utf8");
assert.match(monitorSource,
  /function syncMonitorThumbnailTabBadges\([\s\S]*MonitorBctThumbnailProjection[\s\S]*return diagnostics;/,
  "the active thumbnail path must delegate to the isolated projection renderer");
const decoratorStart = monitorSource.indexOf("function syncMonitorDesktopNumberBadge(");
const decoratorEnd = monitorSource.indexOf("\nfunction ", decoratorStart + 1);
const decorator = monitorSource.slice(decoratorStart, decoratorEnd);
assert.doesNotMatch(decorator, /syncMonitorThumbnailTabBadges\(/,
  "per-image decoration must not re-enter the full thumbnail projection");

function node(className = "") {
  const result = {
    className,
    dataset: {},
    style: {},
    children: [],
    parentElement: null,
    isConnected: true,
    classList: {
      toggle(name, enabled) {
        const names = new Set(String(this.owner.className || "").split(/\s+/).filter(Boolean));
        if (enabled) names.add(name); else names.delete(name);
        this.owner.className = [...names].join(" ");
      },
      owner: null,
    },
    append(child) {
      if (child.parentElement) child.parentElement.children = child.parentElement.children.filter((item) => item !== child);
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

const visual = node("monitor-desktop-thumb-visual");
visual.dataset.desktopId = "desk-a";
visual.dataset.monitorPreviewVirtualLeft = "0";
visual.dataset.monitorPreviewVirtualTop = "0";
visual.dataset.monitorPreviewVirtualWidth = "1000";
visual.dataset.monitorPreviewVirtualHeight = "800";
const chrome = node("monitor-desktop-thumb-window");
chrome.dataset.hwnd = "500";
chrome.style.left = "50%";
chrome.style.top = "0%";
chrome.style.width = "50%";
chrome.style.height = "100%";
chrome.style.zIndex = "9998";
visual.append(chrome);

const context = {
  globalThis: null,
  document: { createElement: () => node() },
  String, Number, Math, Boolean, Map, Set, Object,
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context);
const locations = new Map([["500", { hwnd: "500", desktopId: "desk-a", left: 500, top: 0, width: 500, height: 800, iconic: false, visible: true }]]);
let observedState = "not-called";
const render = () => context.MonitorBctThumbnailProjection.render({
  container: visual,
  // Production can have no legacy ACT/AI state while the BCT/RCC node cache
  // and the exact HWND contract are healthy. That must not suppress badges.
  state: null,
  locations,
  highlightedHwnd: "500",
  numbersForHwnd: (hwnd, state) => {
    observedState = state;
    return hwnd === "500" ? [4, 9, 7, 9] : [];
  },
});
const first = render();
assert.deepEqual({ status:first.status, candidates:first.candidates, matched:first.matched, rendered:first.rendered },
  { status:"RENDERED", candidates:1, matched:1, rendered:1 });
assert.equal(observedState, null,
  "BCT/RCC number projection must run even when legacy ACT/AI state is absent");

const layer = visual.querySelector(".monitor-thumbnail-node-overlay");
assert.ok(layer, "dedicated thumbnail overlay layer must be created");
const windowOverlay = layer.querySelector(".monitor-thumbnail-node-window");
assert.ok(windowOverlay, "exact native-window overlay must be created");
assert.equal(windowOverlay.dataset.hwnd, "500");
assert.equal(windowOverlay.style.left, "50%");
assert.equal(windowOverlay.style.width, "50%");
assert.match(windowOverlay.className, /monitor-bct-node-target-highlighted/);
const badges = windowOverlay.querySelectorAll(".monitor-thumbnail-tab-badge");
assert.equal(badges.length, 1);
assert.equal(badges[0].textContent, "N4/9/7");

render();
assert.equal(visual.querySelectorAll(".monitor-thumbnail-node-overlay").length, 1);
assert.equal(layer.querySelectorAll(".monitor-thumbnail-tab-badge").length, 1);
assert.equal(visual.children.at(-1), layer, "overlay layer must stay above every captured window image");

// The semantic overlay is also renderable from exact Native geometry when the
// capture image is temporarily absent or replaced.
chrome.remove();
render();
const geometryOverlay = layer.querySelector(".monitor-thumbnail-node-window");
assert.ok(geometryOverlay, "native geometry must survive capture DOM replacement");
assert.equal(geometryOverlay.style.left, "50%");
assert.equal(geometryOverlay.style.top, "0%");
assert.equal(geometryOverlay.style.width, "50%");
assert.equal(geometryOverlay.style.height, "100%");
assert.equal(geometryOverlay.querySelector(".monitor-thumbnail-tab-badge").textContent, "N4/9/7");
console.log("PASS: open ChatGPT node overlay survives capture DOM replacement using exact Native geometry");
