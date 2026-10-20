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
  return {
    className,
    dataset: {},
    style: {},
    children: [],
    parentElement: null,
    isConnected: true,
    append(child) { child.parentElement = this; this.children.push(child); },
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
}

const visual = node("monitor-desktop-thumb-visual");
const chrome = node("monitor-desktop-thumb-window");
chrome.dataset.hwnd = "500";
chrome.style.left = "50%";
chrome.style.top = "0%";
chrome.style.zIndex = "9998";
visual.append(chrome);

const context = {
  monitorLastAiState: {},
  monitorBadgeNodeNumbersForHwnd: (hwnd) => hwnd === "500" ? [4, 7, 9] : [],
  document: { createElement: () => node() },
  String, Number, Math,
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
context.syncMonitorThumbnailTabBadges(visual, "monitor-desktop-thumb-window");

const layer = visual.querySelector(".monitor-thumbnail-node-overlay");
assert.ok(layer, "dedicated thumbnail overlay layer must be created");
const badges = layer.querySelectorAll(".monitor-thumbnail-tab-badge");
assert.equal(badges.length, 1);
assert.equal(badges[0].textContent, "N4/7/9");
assert.equal(badges[0].style.left, "50%");
assert.equal(badges[0].style.top, "0%");

context.syncMonitorThumbnailTabBadges(visual, "monitor-desktop-thumb-window");
assert.equal(visual.querySelectorAll(".monitor-thumbnail-node-overlay").length, 1);
assert.equal(layer.querySelectorAll(".monitor-thumbnail-tab-badge").length, 1);
assert.equal(visual.children.at(-1), layer, "overlay layer must stay above every captured window image");
console.log("PASS: open ChatGPT node numbers remain in one dedicated top thumbnail overlay layer");
