"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const source = fs.readFileSync(path.join(__dirname,"../extension/monitor.js"),"utf8");
const start = source.indexOf("async function commitMonitorBctNodeDrop(");
const end = source.indexOf("\nasync function refreshMonitorBctWindowNodes(",start);
assert.ok(start>0 && end>start);
async function scenario(freshRefresh) {
 let resolveSave,rejectSave;
 const promise = new Promise((resolve,reject)=>{resolveSave=resolve;rejectSave=reject;});
 const initial=[
  {conversationKey:"A",scopeId:"team",scopeName:"Team",displayOrder:1,tabIndex:0,tabId:1},
  {conversationKey:"A",scopeId:"team",scopeName:"Team",displayOrder:1,tabIndex:3,tabId:9},
  {conversationKey:"B",scopeId:"team",scopeName:"Team",displayOrder:2,tabIndex:1,tabId:2}
 ];
 const renders=[],statuses=[];
 let calls=0;
 const ctx={
  monitorBctNodeReorderPending:false,
  monitorBctDraggedNodeKey:"A",
  monitorBctWindowNodesCache:initial,
  monitorBctShell:{reorderConversations:(nodes)=>{
    assert.deepEqual(nodes.map((node)=>node.conversationKey),["B","A"],"duplicate UUIDs never enter reorder persistence");
    calls++;return promise;
  }},
  finishMonitorBctNodeDrag(){},
  renderMonitorBctWindowNodes(nodes){renders.push(nodes);},
  setMonitorStatus(...args){statuses.push(args);},
  monitorUniqueBctConversationNodes:(nodes)=>[
    ...new Map(nodes.map((node)=>[node.conversationKey,node])).values()
  ],
  compareMonitorBctNodeDisplayOrder:(a,b)=>a.displayOrder-b.displayOrder,
  Object,Map,Array,String
 };
 vm.createContext(ctx);
 vm.runInContext(source.slice(start,end),ctx);
 const pending=ctx.commitMonitorBctNodeDrop("team","B","after");
 assert.equal(ctx.monitorBctNodeReorderPending,true);
 assert.equal(calls,1);
 assert.equal(ctx.monitorBctWindowNodesCache.find(x=>x.conversationKey==="A").displayOrder,2);
 assert.equal(ctx.monitorBctWindowNodesCache.find(x=>x.conversationKey==="B").displayOrder,1);
 await ctx.commitMonitorBctNodeDrop("team","B","before");
 assert.equal(calls,1,"concurrent reorder must be rejected while saving");
 const fresh=[
  {conversationKey:"A",scopeId:"team",scopeName:"newest",displayOrder:88},
  {conversationKey:"B",scopeId:"team",scopeName:"newest",displayOrder:99}
 ];
 if(freshRefresh){ctx.monitorBctWindowNodesCache=fresh;}
 rejectSave(Error("simulated-failure"));
 await pending;
 assert.equal(ctx.monitorBctNodeReorderPending,false,"pending flag cleared after rejection");
 assert.equal(calls,1);
 if(freshRefresh){
  assert.equal(ctx.monitorBctWindowNodesCache,fresh,"newest state preserved");
  assert.equal(renders.length,1,"do not rerender outdated snapshot");
 } else {
  assert.equal(ctx.monitorBctWindowNodesCache.length,3,"rollback preserves the original observation cache");
  assert.equal(ctx.monitorBctWindowNodesCache[0].displayOrder,1,"old order restored");
  assert.equal(ctx.monitorBctWindowNodesCache[1].displayOrder,1,"duplicate observation keeps the same restored order");
  assert.equal(ctx.monitorBctWindowNodesCache[2].displayOrder,2);
  assert.equal(renders.length,2,"rollback repaint completed");
 }
 assert.equal(statuses.length,1);
}
async function successfulSave(){
 let complete;
 const promise=new Promise(resolve=>{complete=resolve;});
 const ctx={
  monitorBctNodeReorderPending:false,monitorBctDraggedNodeKey:"A",
  monitorBctWindowNodesCache:[{conversationKey:"A",scopeId:"a",displayOrder:1},{conversationKey:"B",scopeId:"a",displayOrder:2}],
  monitorBctShell:{reorderConversations:()=>promise},
  finishMonitorBctNodeDrag(){},renderMonitorBctWindowNodes(){},setMonitorStatus(){},
  monitorUniqueBctConversationNodes:(nodes)=>[
    ...new Map(nodes.map((node)=>[node.conversationKey,node])).values()
  ],
  compareMonitorBctNodeDisplayOrder:(a,b)=>a.displayOrder-b.displayOrder,Object,Map,Array,String
 };
 vm.createContext(ctx);vm.runInContext(source.slice(start,end),ctx);
 const task=ctx.commitMonitorBctNodeDrop("a","B","after");
 assert.equal(ctx.monitorBctNodeReorderPending,true);
 complete(true);await task;
 assert.equal(ctx.monitorBctNodeReorderPending,false);
 assert.equal(ctx.monitorBctWindowNodesCache[0].displayOrder,2);
}
async function crossScopeMove(destinationGroupKey, destinationScopeName, expectedScopeName) {
 const updates=[],reorders=[],statuses=[];
 const ctx={
  monitorBctNodeReorderPending:false,monitorBctDraggedNodeKey:"A",
  monitorBctWindowNodesCache:[
   {conversationKey:"A",title:"Worker A",scopeId:"team-a",scopeName:"Team A",roleTags:["Worker","Review"]},
   {conversationKey:"B",title:"Worker B",scopeId:"team-b",scopeName:"Team B",roleTags:["Manager"]}
  ],
  monitorBctShell:{
   updateConversationScope:async(node,values)=>{updates.push({node,values});return {};},
   reorderConversations:()=>{reorders.push(true);return Promise.resolve({});}
  },
  finishMonitorBctNodeDrag(){},renderMonitorBctWindowNodes(nodes){ctx.renders.push(nodes);},
  refreshMonitorBctWindowNodes:async()=>{ctx.refreshed=(ctx.refreshed||0)+1;},
  renders:[],
  setMonitorStatus(...args){statuses.push(args);},
  monitorUniqueBctConversationNodes:(nodes)=>[...new Map(nodes.map((node)=>[node.conversationKey,node])).values()],
  compareMonitorBctNodeDisplayOrder:()=>0,Object,Map,Array,String
 };
 vm.createContext(ctx);vm.runInContext(source.slice(start,end),ctx);
 const task=ctx.commitMonitorBctNodeDrop(destinationGroupKey,"","append",destinationScopeName);
 const optimistic=ctx.monitorBctWindowNodesCache.find((node)=>node.conversationKey==="A");
 assert.equal(optimistic.scopeId,destinationGroupKey==="__unassigned__"?"":destinationGroupKey,
   "the card moves immediately instead of returning to the old group while saving");
 assert.equal(optimistic.scopeName,expectedScopeName);
 assert.equal(ctx.renders.length,1,"the optimistic card location is rendered before the metadata write resolves");
 await task;
 assert.equal(ctx.monitorBctNodeReorderPending,false);
 assert.equal(reorders.length,0,"cross-scope drops use the same metadata update path as the context menu");
 assert.equal(updates.length,1);
 assert.equal(updates[0].node.conversationKey,"A");
 assert.equal(updates[0].values.displayName,"Worker A");
 assert.equal(updates[0].values.scopeName,expectedScopeName);
 assert.deepEqual(updates[0].values.roleTags,["Worker","Review"],"role tags survive scope changes");
 assert.equal(ctx.refreshed,1,"scope changes re-read authoritative Monitor state");
 assert.equal(statuses.length,1);
}
(async()=>{
 await scenario(false);
 await scenario(true);
 await successfulSave();
 await crossScopeMove("__unassigned__","","");
 await crossScopeMove("team-b","Team B","Team B");
 assert.match(source,/monitorBctPointerDrag \|\| monitorBctNodeReorderPending\) return/);
 console.log(JSON.stringify({status:"PASS",cases:5,coverage:"save-failure-rollback,refresh-generation-guard,serial-save-success,scope-move-to-unassigned,scope-move-to-network"}));
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
