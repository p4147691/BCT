// Isolated BCT/RCC thumbnail label projection test. No browser or native calls.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname,"../extension/monitor.js"),"utf8");
const projectionSource = fs.readFileSync(path.join(__dirname,"../extension/monitor-bct-thumbnail-projection.js"),"utf8");
const start = source.indexOf("function monitorBadgeNodeNumbersForHwnd(");
const end = source.indexOf("function syncMonitorDesktopNumberBadge(", start);
assert.ok(start > 0 && end > start);
const fn = source.slice(start,end);
const state = { dummy:true };
const nodes = [
  {windowId:491,nodeLabel:"N4",title:"첫 탭",conversationKey:"a"},
  {windowId:491,nodeLabel:"N9",title:"둘째 탭",conversationKey:"c"},
  {windowId:491,nodeLabel:"N7",title:"셋째 탭",conversationKey:"b"},
  {windowId:319,nodeLabel:"N3",title:"오류 병목 감시 측정기",conversationKey:"c"},
  {windowId:491,nodeLabel:"N9",title:"같은 노드 중복 관측",conversationKey:"c"},
  {windowId:491,nodeLabel:"",title:"대화 준비",conversationKey:""}
];
const ctx = {
  monitorBctWindowNodesCache:nodes,
  monitorLastAiState:state,
  monitorDisplayHwndForBrowserWindowId:(windowId)=>({491:"5000",319:"6000"})[windowId]||"",
  monitorActNodeNumbersForHwnd:()=>[99],
  String,Number,Array,Set
};
vm.createContext(ctx);
vm.runInContext(fn,ctx);
const lookup=(hwnd)=>Array.from(ctx.monitorBadgeNodeNumbersForHwnd(hwnd,state));
assert.deepEqual(lookup("5000"),[4,9,7],"shared Chrome HWND must preserve Chrome tab order");
assert.deepEqual(lookup("6000"),[3],"other HWND must not leak labels");
assert.deepEqual(lookup("7000"),[],"unmapped HWND must not show fabricated labels");
assert.deepEqual(lookup(""),[],"empty HWND must remain empty");
assert.deepEqual(lookup("5000"),[4,9,7],"pending conversation must not fabricate a permanent label");
ctx.monitorBctWindowNodesCache=[];
assert.deepEqual(lookup("5000"),[],"authoritative empty directory must not use obsolete ACT labels");
ctx.monitorBctWindowNodesCache=null;
assert.deepEqual(lookup("5000"),[99],"legacy fallback limited to before BCT first read");
assert.match(projectionSource,/badge\.textContent\s*=\s*`N\$\{numbers\.join\("\/"\)\}`/);
assert.doesNotMatch(projectionSource,/monitor-thumbnail-node-chip-list/);
assert.doesNotMatch(projectionSource,/selectedNodeKey/);
assert.match(projectionSource,/windowLayer\.style\.zIndex\s*=\s*String\(windowZIndex\(img\)\)/);
assert.match(source,/monitorBctShell\.displayWindowNodes/);
assert.match(source,/syncMonitorAllDesktopThumbnailNodeBadges\(\)/);
assert.match(source,/MONITOR_BCT_PROJECTION_CONVERGENCE_DELAYS_MS = Object\.freeze\(\[0, 450, 1400\]\)/);
assert.match(source,/scheduleMonitorBctProjectionConvergence\("desktop-topology"\)/);
assert.match(source,/monitorBctProjectionConvergenceAttempt >= MONITOR_BCT_PROJECTION_CONVERGENCE_DELAYS_MS\.length/);
assert.match(source,/function monitorDisplayHwndForBrowserWindowId\(/);
assert.match(source,/resolveMonitorBctNodeDisplayHwnd\(node\)\.then/);
assert.match(source,/resolveMonitorBctNodeHwnd\(node\)\.then/);
assert.match(source,/location\.textContent = monitorBctNodeLocationText\(node, desktopPosition\)/);
assert.match(source,/row\.append\(number, body\)/,
  "the node list exposes only node number, title, and desktop location");
assert.doesNotMatch(source,/monitor-bct-node-presence|presence\.textContent\s*=/,
  "generation state is not a visible node-list column");
assert.doesNotMatch(source,/id="monitorLocalLlmOpen"/);
assert.doesNotMatch(source,/id="monitorNodeCols[23]"/);
assert.doesNotMatch(source,/id="monitorRccRescan"/);
assert.match(source,/id="monitorBctRecover" type="button" title=/);
assert.doesNotMatch(source,/id="monitorBctRecover" type="button" disabled/);
const css = fs.readFileSync(path.join(__dirname,"../extension/monitor.css"),"utf8");
assert.match(css,/\.monitor-bct-nodes\[data-columns="3"\]/);
assert.match(css,/\.monitor-bct-node-list\s*\{[^}]*grid-template-columns:repeat\(3,minmax\(0,1fr\)\)!important/s);
console.log("PASS: BCT/RCC ordered multi-tab labels, exact HWND separation, natural z-order, 3-column default, and guarded recovery buttons");
