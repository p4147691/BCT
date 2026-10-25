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
      add(name) { const names=new Set(String(this.owner.className||'').split(/\s+/).filter(Boolean));names.add(name);this.owner.className=[...names].join(' '); },
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

// Two physical Chrome windows can occupy the same screen rectangle. Their
// badges must use different corners instead of covering one another.
const overlappingChrome = node("monitor-desktop-thumb-window");
overlappingChrome.dataset.hwnd = "600";
overlappingChrome.style.left = "50%";
overlappingChrome.style.top = "0%";
overlappingChrome.style.width = "50%";
overlappingChrome.style.height = "100%";
visual.append(overlappingChrome);
locations.set("600", { hwnd: "600", desktopId: "desk-a", left: 500, top: 0, width: 500, height: 800, iconic: false, visible: true });
const collisionResult = context.MonitorBctThumbnailProjection.render({
  container: visual,
  state: null,
  locations,
  numbersForHwnd: (hwnd) => hwnd === "500" ? [14] : (hwnd === "600" ? [13] : []),
});
assert.equal(collisionResult.rendered, 2);
assert.equal(collisionResult.repositioned, 1);
assert.equal(collisionResult.unresolvedCollisions, 0);
const collisionBadges = layer.querySelectorAll(".monitor-thumbnail-tab-badge");
assert.deepEqual(new Set(collisionBadges.map((badge) => badge.textContent)), new Set(["N14", "N13"]));
assert.deepEqual(new Set(collisionBadges.map((badge) => badge.dataset.anchor)), new Set(["top-left", "top-right"]));

// Re-rendering the same topology is deterministic and does not accumulate
// extra overlay nodes or drift the chosen anchors.
const collisionRepeat = context.MonitorBctThumbnailProjection.render({
  container: visual,
  state: null,
  locations,
  numbersForHwnd: (hwnd) => hwnd === "500" ? [14] : (hwnd === "600" ? [13] : []),
});
assert.equal(collisionRepeat.repositioned, 1);
const repeatedAnchors = new Map(layer.querySelectorAll(".monitor-thumbnail-tab-badge")
  .map((badge) => [badge.dataset.hwnd, badge.dataset.anchor]));
const firstAnchors = new Map(collisionBadges.map((badge) => [badge.dataset.hwnd, badge.dataset.anchor]));
assert.deepEqual(repeatedAnchors, firstAnchors);
console.log("PASS: open ChatGPT node overlays survive capture replacement and avoid badge collisions");


// Native Z-order and selected per-tab badges must not be conflated.
visual.append(chrome);
chrome.dataset.nativeZIndex="9000";
overlappingChrome.dataset.nativeZIndex="9800";
const sourceNodes=new Map([
 ["500", [{number:37,key:"one:tab37",activity:"pause"},{number:38,key:"one:tab38",activity:"play"},{number:39,key:"one:tab39",activity:"pause"}]],
 ["600", [{number:40,key:"two:tab40",activity:"pause"},{number:41,key:"two:tab41",activity:"complete"}]]
]);
const selectedView=context.MonitorBctThumbnailProjection.render({
 container:visual,state:null,locations,
 numbersForHwnd:()=>[],
 nodesForHwnd:(hwnd)=>sourceNodes.get(hwnd)||[],
 selectedNodeKey:"one:tab38"
});
assert.equal(selectedView.rendered,2);
assert.equal(selectedView.zStackedWindows,2);
assert.equal(selectedView.hiddenWindows,0);
assert.equal(selectedView.zOrderConfirmed,true);
const ordered=layer.querySelectorAll(".monitor-thumbnail-z-row");
assert.deepEqual(ordered.map(item=>item.dataset.hwnd),["600","500"],"front Z HWND before rear");
const nodes=layer.querySelectorAll(".monitor-thumbnail-node-chip");
assert.equal(nodes.length,5);
const chosen=nodes.find(x=>x.dataset.nodeKey==="one:tab38");
assert.ok(chosen.className.includes("is-selected"),"only N38 highlighted");
assert.equal(nodes.filter(x=>x.className.includes("is-selected")).length,1);
assert.equal(chosen.children[0].textContent,"▶");
context.MonitorBctThumbnailProjection.highlight(visual,"two:tab41");
assert.equal(nodes.filter(x=>x.className.includes("is-selected")).length,1);
assert.ok(nodes.find(x=>x.dataset.nodeKey==="two:tab41").className.includes("is-selected"));
console.log("PASS: exact N38 highlighting, native Z order, multi-tab activity");

const rear = [["700",8700],["800",8600],["900",8500]];
for (const [hwnd,z] of rear) {
 const img=node("monitor-desktop-thumb-window");
 img.dataset.hwnd=hwnd; img.dataset.nativeZIndex=String(z);
 Object.assign(img.style,{left:"50%",top:"0%",width:"50%",height:"100%"});
 visual.append(img);
 locations.set(hwnd,{hwnd,desktopId:"desk-a",left:500,top:0,width:500,height:800,iconic:false,visible:true});
 sourceNodes.set(hwnd,[{number:Number(hwnd),key:"rear:"+hwnd,activity:"pause"}]);
}
const crowded=context.MonitorBctThumbnailProjection.render({
 container:visual,state:null,locations,numbersForHwnd:()=>[],
 nodesForHwnd:hwnd=>sourceNodes.get(hwnd)||[],selectedNodeKey:"rear:900"
});
assert.equal(crowded.zStackedWindows,5);
assert.equal(crowded.hiddenWindows,2,"bounded rail reserves space for hidden count");
const rows=layer.querySelectorAll(".monitor-thumbnail-z-row");
assert.deepEqual(rows.map(x=>x.dataset.hwnd),["600","500","900"],"selected rear remains visible within three rows");
assert.ok(rows.at(-1).querySelector(".monitor-thumbnail-node-chip").className.includes("is-selected"));
console.log("PASS: crowded 5 HWND Z rail with selected rear visible");
