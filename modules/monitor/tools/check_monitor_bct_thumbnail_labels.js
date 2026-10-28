// Exact HWND and Chrome tab-order contract for display-only thumbnail labels.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname,"../extension/monitor.js"),"utf8");
const projectionSource = fs.readFileSync(path.join(__dirname,"../extension/monitor-bct-thumbnail-projection.js"),"utf8");
const start=source.indexOf("function monitorBadgeNodeNumbersForHwnd(");
const end=source.indexOf("\nfunction ", start+1);
assert.ok(start>0 && end>start,"node token resolver must exist");
const nodes=[
  {windowId:491,tabId:42,tabIndex:0,nodeLabel:"N4",conversationKey:"a"},
  {windowId:491,tabId:44,tabIndex:2,nodeLabel:"N9",conversationKey:"b"},
  {windowId:491,tabId:45,tabIndex:3,nodeLabel:"N7",conversationKey:"c"},
  {windowId:319,tabId:51,tabIndex:0,nodeLabel:"N3",conversationKey:"d"},
];
const ctx={
  monitorBctWindowNodesCache:nodes,
  monitorLastAiState:{},
  monitorBctDisplaySessionHwnd:(windowId)=>({491:"5000",319:"6000"})[windowId]||"",
  monitorBrowserVisualTabsForWindow:(windowId)=>windowId===491
    ? [{tabId:42,tabIndex:0},{tabId:43,tabIndex:1},{tabId:44,tabIndex:2},{tabId:45,tabIndex:3}]
    :windowId===319?[{tabId:51,tabIndex:0}]:[],
  monitorActNodeNumbersForHwnd:()=>[99],
  String,Number,Array,Set,Map,
};
vm.createContext(ctx);
vm.runInContext(source.slice(start,end),ctx);
const lookup=(hwnd,options)=>Array.from(ctx.monitorBadgeNodeNumbersForHwnd(hwnd,ctx.monitorLastAiState,options));
assert.deepEqual(lookup("5000"),[4,"?",9,7],"real Chrome tab order and UUID-less slot preserved");
assert.deepEqual(lookup("6000"),[3],"other Chrome window isolated by HWND");
assert.deepEqual(lookup("7000"),[],"unmapped window has no fabricated node");
assert.deepEqual(lookup(""),[],"invalid HWND has no fabricated node");
const exact=lookup("5000",{includeTabIds:true}).map(x=>[x.token,x.tabId]);
assert.deepEqual(exact,[[4,42],["?",43],[9,44],[7,45]],
  "every Chrome tab maintains its own selectable tabId");
ctx.monitorBctWindowNodesCache=[];
assert.deepEqual(lookup("5000"),[],"authoritative empty membership suppresses stale labels");
ctx.monitorBctWindowNodesCache=null;
assert.deepEqual(lookup("5000"),[99],"legacy fallback limited to before first BCT read");
assert.match(projectionSource,/part\.textContent = token;/,"each node number renders without N prefix");
assert.doesNotMatch(projectionSource,/prefix\.textContent = "N"/,"visual prefix removed only");
assert.match(projectionSource,/windowLayer\.style\.zIndex = String\(windowZIndex\(img\)\)/);
assert.match(source,/monitorBctShell\.displayWindowNodes/);
assert.match(source,/syncMonitorAllDesktopThumbnailNodeBadges\(\)/);
assert.match(source,/monitorBctNodeSelectionKey\(node\)/);
console.log("PASS: current-session HWND, UUID-less exact tab IDs, ordered numeric-only thumbnail labels");
