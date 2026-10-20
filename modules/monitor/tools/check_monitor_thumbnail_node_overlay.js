"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../extension/monitor.js"), "utf8");
const start = source.indexOf("function syncMonitorThumbnailTabBadges(");
const end = source.indexOf("\nfunction syncMonitorBctNodeLocationLabels(", start);
assert.ok(start > 0 && end > start, "thumbnail badge renderer must be extractable");

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
  monitorLastAiState: {},
  monitorBctNodeHighlightedHwnd: "500",
  monitorWindowDesktopLocations: new Map([["500", { hwnd: "500", desktopId: "desk-a", left: 500, top: 0, width: 500, height: 800, iconic: false, visible: true }]]),
  monitorBadgeNodeNumbersForHwnd: (hwnd) => hwnd === "500" ? [4, 7, 9] : [],
  document: { createElement: () => node() },
  String, Number, Math, Boolean, Map, Set,
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
context.syncMonitorThumbnailTabBadges(visual, "monitor-desktop-thumb-window");

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
assert.equal(badges[0].textContent, "N4/7/9");

context.syncMonitorThumbnailTabBadges(visual, "monitor-desktop-thumb-window");
assert.equal(visual.querySelectorAll(".monitor-thumbnail-node-overlay").length, 1);
assert.equal(layer.querySelectorAll(".monitor-thumbnail-tab-badge").length, 1);
assert.equal(visual.children.at(-1), layer, "overlay layer must stay above every captured window image");

// The semantic overlay is also renderable from exact Native geometry when the
// capture image is temporarily absent or replaced.
chrome.remove();
context.syncMonitorThumbnailTabBadges(visual, "monitor-desktop-thumb-window");
const geometryOverlay = layer.querySelector(".monitor-thumbnail-node-window");
assert.ok(geometryOverlay, "native geometry must survive capture DOM replacement");
assert.equal(geometryOverlay.style.left, "50%");
assert.equal(geometryOverlay.style.top, "0%");
assert.equal(geometryOverlay.style.width, "50%");
assert.equal(geometryOverlay.style.height, "100%");
assert.equal(geometryOverlay.querySelector(".monitor-thumbnail-tab-badge").textContent, "N4/7/9");
console.log("PASS: open ChatGPT node overlay survives capture DOM replacement using exact Native geometry");
