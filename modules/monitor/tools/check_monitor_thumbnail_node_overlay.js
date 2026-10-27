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
  ["500", [33, 35, 45, 35]],
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
assert.equal(overlays.get("500").querySelector(".monitor-thumbnail-tab-badge").textContent, "N33/35/45");
assert.equal(
  overlays.get("600").querySelector(".monitor-thumbnail-tab-badge").textContent,
  "N7/8/9/10/11/12/13/14",
  "all tabs must remain visible; wrapping belongs to CSS and no +n abbreviation is allowed",
);
assert.equal(layer.querySelector(".monitor-thumbnail-z-rail"), null,
  "collision rails must not exist in the simplified projection");
assert.equal(layer.querySelector(".monitor-thumbnail-node-chip"), null,
  "per-node chips and state icons are outside the static node-label layer");
assert.equal(first.repositioned, 0);
assert.equal(first.unresolvedCollisions, 0);

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

console.log("PASS: simple top-left N labels keep tab order, wrap without truncation, and share physical HWND z-order");
