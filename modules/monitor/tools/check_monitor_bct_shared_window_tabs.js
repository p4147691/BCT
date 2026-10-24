// Offline UTF-8 focused acceptance: no Chrome/Monitor/RCC access or side effects.
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../extension/monitor.js"),"utf8");
const css=fs.readFileSync(path.join(__dirname,"../extension/monitor.css"),"utf8");
const first=source.indexOf("function compareMonitorBctNodeDisplayOrder(");
const last=source.indexOf("function renderMonitorBctWindowNodes(",first);
assert(first>0&&last>first,"BCT grouping and focus adapter projection source");
const adapterSource=fs.readFileSync(path.join(__dirname,"../extension/browser/tab-focus-adapter.js"),"utf8");
const calls=[],messages=[];
const tabs=new Map(),windows=new Map();
const chromeApi={
  tabs:{
    get:async(id)=>{if(!tabs.has(id))throw Error("TAB_NOT_FOUND");return {...tabs.get(id)};},
    update:async(id,update)=>{calls.push(["tab",id,update]);const tab=tabs.get(id);tab.active=update.active;return {...tab};}
  },
  windows:{
    get:async(id)=>({id,focused:windows.get(id)===true}),
    update:async(id,update)=>{calls.push(["window",id,update]);windows.set(id,update.focused===true);return {id,focused:true};}
  }
};
const ctx={globalThis:null,Map,Set,Array,Object,Number,String,Date,Promise,URL,RegExp};
ctx.globalThis=ctx;
vm.createContext(ctx);
vm.runInContext(adapterSource,ctx);
const adapter=ctx.MonitorTabFocusAdapter.create(chromeApi);
ctx.chrome={runtime:{sendMessage:async(msg)=>{messages.push(msg);return adapter.focus(msg);}}};
vm.runInContext(source.slice(first,last)+"\n;globalThis.group=monitorBctSharedWindowGroups;globalThis.focus=monitorFocusBctSharedWindowTab;",ctx);
const uuid=["6adcfacf-c7e8-83ee-8ecc-2ff0dbfe3b54","6adcfada-7374-83ee-9ae1-695747fedafb",
"6adcfae3-7dcc-83e8-b4d4-7b852dcdbf8e","6adbf646-cbd4-83ee-b1cc-526c4749ab9b"];
function node(i,overrides={}) {
  return {instanceId:"rcc-one",sessionId:"session-one",instanceState:"OPEN",tabId:100+i,windowId:200,
    tabIndex:i,conversationKey:uuid[i],scopeId:i===2?"other-scope":"default",scopeName:i===2?"다른 작업":"개별 작업",
    nodeLabel:"N"+(i+37),active:i===0,displayStale:false,instanceCached:false,presence:"OPEN",generating:i===1,...overrides};
}
(async()=>{
 const sourceNodes=[node(0),node(1),node(2),node(3)];
 const groups=ctx.group(sourceNodes);
 assert.equal(groups.length,1,"one Chrome window independently of tab/scope");
 assert.equal(groups[0].tabCount,4);
 assert.equal(groups[0].entries.length,4,"four distinct conversations visible");
 assert.equal(groups[0].__window_group_members.length,4,"reuse window group members");
 assert.deepEqual(Array.from(groups[0].entries,(e)=>e.node.tabId),[100,101,102,103]);
 assert.equal(groups[0].entries[1].node.generating,true,"per-tab generating status");
 const extra=node(1,{tabId:111,tabIndex:4,active:true,generating:false});
 const duplicates=ctx.group([...sourceNodes,extra]);
 assert.equal(duplicates.length,1);
 assert.equal(duplicates[0].tabCount,5);
 assert.equal(duplicates[0].entries.length,4,"same UUID one semantic row");
 const duplicate=duplicates[0].entries.find((e)=>e.node.conversationKey===uuid[1]);
 assert.equal(duplicate.attachments.length,2);
 assert.equal(duplicate.node.tabId,111,"active attachment preferred for tab selection");
 assert(duplicate.attachments.some((item)=>item.generating===true),"activity not lost when another duplicate is selected");
 const moved=ctx.group([node(0),node(1,{windowId:201}),node(2),node(3)]);
 assert.equal(moved.length,2,"physical window move invalidates old grouping");
 assert.deepEqual(Array.from(moved.find(g=>g.windowId===201).entries,e=>e.node.tabId),[101]);
 const stale=node(1,{displayStale:true,instanceCached:true,instanceState:"UNAVAILABLE"});
 assert.equal((await ctx.focus(stale)).status,"NOT_APPLIED");
 assert.equal((await ctx.focus(node(1,{conversationKey:""}))).status,"NOT_APPLIED");
 assert.equal(messages.length,0,"no focus on stale or missing UUID");
 assert.equal(calls.length,0,"no browser effects before an exact user click");
 const n=node(0);
 tabs.set(n.tabId,{id:n.tabId,windowId:n.windowId,url:"https://chatgpt.com/c/"+n.conversationKey,active:false});
 let receipt=await ctx.focus(n);
 assert.equal(receipt.status,"APPLIED");
 assert.equal(messages.length,1);
 assert.deepEqual(calls.map(x=>x[0]),["tab","window"],"single action after explicit click");
 const other=node(1);
 tabs.set(other.tabId,{id:other.tabId,windowId:other.windowId,url:"https://chatgpt.com/c/"+uuid[3],active:false});
 const before=calls.length;
 receipt=await ctx.focus(other);
 assert.equal(receipt.status,"NOT_APPLIED","URL UUID mismatch fails closed");
 assert.equal(calls.length,before,"wrong focus performs no effect");
 assert.equal(messages.length,2,"one message per valid explicit focus attempt, no retry");
 const shifted=node(2,{windowId:202});
 tabs.set(shifted.tabId,{id:shifted.tabId,windowId:200,url:"https://chatgpt.com/c/"+shifted.conversationKey,active:false});
 receipt=await ctx.focus(shifted);
 assert.equal(receipt.status,"NOT_APPLIED","tab moved to different window: no wrong focus");
 assert.equal(calls.length,before);
 assert.match(source,/if\(isShared\)\s*\{[\s\S]*?monitorFocusBctSharedWindowTab\(node\)/,"only a shared row click focuses its tab");
 assert.match(source,/if\(isShared\)return;\s*row\.classList\.add\("monitor-bct-node-switch-pending"\)/,"shared row double-click cannot also move desktop");
 assert.match(source,/monitorBctCollapsedWindowCards/);
 assert.match(source,/sharedWindowScope\.set\(group\.key/,"cross-scope tabs use one card");
 assert.match(source,/rowContainer\.append\(row\)/);
 assert.match(source,/row\.parentElement === list/,"nested group card is not an invalid drag insertion target");
 assert.match(source,/if \(event\.detail > 1\) return/,"double click does not dispatch twice");
 assert.match(source,/const isGenerating = entry\.attachments\.some/,"per-UUID activity merged");
 assert.match(css,/\.monitor-bct-window-tab-row\[aria-selected="true"\]/);
 assert(!source.includes("BCT_SHARED_WINDOW_RELOAD"),"no invented reload path");
 assert(Buffer.from("Chrome 창 · 5개 탭","utf8").toString("utf8").includes("개 탭"),"UTF-8 round trip");
 console.log("PASS: shared Chrome window rows, cross-scope grouping, duplicate UUID attachments, generating, move, stale, exact click focus, wrong-window/UUID fail-closed, UTF-8");
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
