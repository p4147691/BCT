// Isolated BCT/RCC thumbnail label projection test. No browser or native calls.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname,"../extension/monitor.js"),"utf8");
const start = source.indexOf("function monitorBadgeNodeNumbersForHwnd(");
const end = source.indexOf("function syncMonitorDesktopNumberBadge(", start);
assert.ok(start > 0 && end > start);
const fn = source.slice(start,end);
const state = { dummy:true };
const nodes = [
  {windowId:491,nodeLabel:"N5",title:"묶음 지시 최적화",conversationKey:"b"},
  {windowId:491,nodeLabel:"N4",title:"평점 조회 방식 조사",conversationKey:"a"},
  {windowId:319,nodeLabel:"N3",title:"오류 병목 감시 측정기",conversationKey:"c"},
  {windowId:491,nodeLabel:"N5",title:"같은 노드 중복 관측",conversationKey:"b"},
  {windowId:491,nodeLabel:"",title:"대화 준비",conversationKey:""}
];
const ctx = {
  monitorBctWindowNodesCache:nodes,
  monitorLastAiState:state,
  monitorHwndForBrowserWindowId:(windowId)=>({491:"5000",319:"6000"})[windowId]||"",
  monitorActNodeNumbersForHwnd:()=>[99],
  String,Number,Array,Set
};
vm.createContext(ctx);
vm.runInContext(fn,ctx);
const lookup=(hwnd)=>Array.from(ctx.monitorBadgeNodeNumbersForHwnd(hwnd,state));
assert.deepEqual(lookup("5000"),[4,5],"shared Chrome HWND must show all RCC node labels");
assert.deepEqual(lookup("6000"),[3],"other HWND must not leak labels");
assert.deepEqual(lookup("7000"),[],"unmapped HWND must not show fabricated labels");
assert.deepEqual(lookup(""),[],"empty HWND must remain empty");
assert.deepEqual(lookup("5000"),[4,5],"pending conversation must not fabricate a permanent label");
ctx.monitorBctWindowNodesCache=[];
assert.deepEqual(lookup("5000"),[],"authoritative empty directory must not use obsolete ACT labels");
ctx.monitorBctWindowNodesCache=null;
assert.deepEqual(lookup("5000"),[99],"legacy fallback limited to before BCT first read");
assert.match(source,/badge\.textContent="N" \+ numbers\.join\("\/"\)/);
assert.match(source,/monitorBctWindowNodesCache = monitorBctShell\.windowNodes\(state\)/);
assert.match(source,/syncMonitorAllDesktopThumbnailNodeBadges\(\)/);
assert.match(source,/location\.textContent = desktopPosition >= 0/);
assert.match(source,/presence\.textContent = node\.generating/);
assert.doesNotMatch(source,/id="monitorLocalLlmOpen"/);
assert.match(source,/id="monitorNodeCols3"/);
assert.match(source,/id="monitorRccRescan"/);
assert.match(source,/type="button" disabled title="Supervisor/);
const css = fs.readFileSync(path.join(__dirname,"../extension/monitor.css"),"utf8");
assert.match(css,/\.monitor-bct-nodes\[data-columns="3"\]/);
assert.match(css,/@media \(max-width:450px\)/);
console.log("PASS: BCT/RCC multi-tab identity, N? pending, native HWND separation, no stale ACT fallback, 2/3-column UI, guarded restart menu");
