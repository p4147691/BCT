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
  refreshMonitorBctWindowNodes:async()=>{},
  renderMonitorBctWindowNodes(nodes){renders.push(nodes);},
  setMonitorStatus(...args){statuses.push(args);},
  monitorUniqueBctConversationNodes:(nodes)=>[
    ...new Map(nodes.map((node)=>[node.conversationKey,node])).values()
  ],
  monitorBctNodeRoleRank:()=>2,
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
 assert.equal(statuses.length,2,"a second drop must explain that the first save is still pending");
}
async function successfulSave(){
 let complete;
 const promise=new Promise(resolve=>{complete=resolve;});
 const ctx={
  monitorBctNodeReorderPending:false,monitorBctDraggedNodeKey:"",
  monitorBctWindowNodesCache:[{conversationKey:"A",scopeId:"a",displayOrder:1},{conversationKey:"B",scopeId:"a",displayOrder:2}],
  monitorBctShell:{reorderConversations:()=>promise},
  finishMonitorBctNodeDrag(){},refreshMonitorBctWindowNodes:async()=>{},renderMonitorBctWindowNodes(){},setMonitorStatus(){},
  monitorUniqueBctConversationNodes:(nodes)=>[
    ...new Map(nodes.map((node)=>[node.conversationKey,node])).values()
  ],
  monitorBctNodeRoleRank:()=>2,
  compareMonitorBctNodeDisplayOrder:(a,b)=>a.displayOrder-b.displayOrder,Object,Map,Array,String
 };
 vm.createContext(ctx);vm.runInContext(source.slice(start,end),ctx);
 const task=ctx.commitMonitorBctNodeDrop("a","B","after","","A");
 assert.equal(ctx.monitorBctNodeReorderPending,true);
 complete(true);await task;
 assert.equal(ctx.monitorBctNodeReorderPending,false);
 assert.equal(ctx.monitorBctWindowNodesCache[0].displayOrder,2);
}
async function pinnedCoordinatorWorkerReorder(){
 const saved=[];
 const ctx={
  monitorBctNodeReorderPending:false,monitorBctDraggedNodeKey:"W2",
  monitorBctWindowNodesCache:[
   {conversationKey:"M",scopeId:"team",displayOrder:1,roleTags:["Manager"]},
   {conversationKey:"W1",scopeId:"team",displayOrder:2,roleTags:[]},
   {conversationKey:"W2",scopeId:"team",displayOrder:3,roleTags:[]}
  ],
  monitorBctShell:{reorderConversations:async(nodes)=>{saved.push(nodes.map(node=>node.conversationKey));}},
  finishMonitorBctNodeDrag(){},refreshMonitorBctWindowNodes:async()=>{},renderMonitorBctWindowNodes(){},setMonitorStatus(){},
  monitorUniqueBctConversationNodes:(nodes)=>nodes,
  monitorBctNodeRoleRank:(node)=>node.roleTags?.includes("Manager")?1:2,
  compareMonitorBctNodeDisplayOrder:(a,b)=>a.displayOrder-b.displayOrder,Object,Map,Array,String
 };
 vm.createContext(ctx);vm.runInContext(source.slice(start,end),ctx);
 await ctx.commitMonitorBctNodeDrop("team","W1","before","","W2");
 assert.deepEqual(saved[0],["M","W2","W1"],"Manager stays first while workers keep the dropped order");
}
async function uuidlessPlaceholderDoesNotRejectDurableReorder(){
 const saved=[];
 const ctx={
  monitorBctNodeReorderPending:false,monitorBctDraggedNodeKey:"B",
  monitorBctWindowNodesCache:[
   {conversationKey:"A",scopeId:"",displayOrder:1,roleTags:[]},
   {conversationKey:"",scopeId:"",displayOrder:0,roleTags:[],tabId:99},
   {conversationKey:"B",scopeId:"",displayOrder:2,roleTags:[]}
  ],
  monitorBctShell:{reorderConversations:async(nodes)=>{saved.push(nodes.map(node=>node.conversationKey));}},
  finishMonitorBctNodeDrag(){},refreshMonitorBctWindowNodes:async()=>{},renderMonitorBctWindowNodes(){},setMonitorStatus(){},
  monitorUniqueBctConversationNodes:(nodes)=>nodes,
  monitorBctNodeRoleRank:()=>2,
  compareMonitorBctNodeDisplayOrder:(a,b)=>a.displayOrder-b.displayOrder,Object,Map,Array,String,Boolean
 };
 vm.createContext(ctx);vm.runInContext(source.slice(start,end),ctx);
 await ctx.commitMonitorBctNodeDrop("__unassigned__","A","before","","B");
 assert.deepEqual(saved[0],["B","A"],"an N? placeholder stays visible but never enters the Core reorder payload");
}
async function uuidlessNodeCanReorderInsideItsCurrentList(){
 const renders=[],coreWrites=[];
 const localOrder=new Map();
 const ctx={
  monitorBctNodeReorderPending:false,monitorBctDraggedNodeKey:"pending-tab",
  monitorBctWindowNodesCache:[
   {conversationKey:"A",selectionKey:"node-a",scopeId:"",displayOrder:1,roleTags:[]},
   {conversationKey:"",selectionKey:"pending-tab",scopeId:"",displayOrder:2,roleTags:[]},
   {conversationKey:"B",selectionKey:"node-b",scopeId:"",displayOrder:3,roleTags:[]}
  ],
  monitorBctShell:{reorderConversations:async(nodes)=>{coreWrites.push(nodes);}},
  monitorBctNodeOrderByScope:localOrder,monitorBctNodeOrderReady:false,
  monitorBctNodeSelectionKey:(node)=>node.selectionKey,
  finishMonitorBctNodeDrag(){},refreshMonitorBctWindowNodes:async()=>{},renderMonitorBctWindowNodes(nodes){renders.push(nodes);},setMonitorStatus(){},
  monitorUniqueBctConversationNodes:(nodes)=>nodes,
  monitorBctNodeRoleRank:()=>2,
  compareMonitorBctNodeDisplayOrder:(a,b)=>a.displayOrder-b.displayOrder,Object,Map,Array,String,Boolean
 };
 vm.createContext(ctx);vm.runInContext(source.slice(start,end),ctx);
 await ctx.commitMonitorBctNodeDrop("__unassigned__","node-a","before","","pending-tab");
 assert.deepEqual(localOrder.get("__unassigned__"),["pending-tab","node-a","node-b"]);
 assert.equal(coreWrites.length,0,"moving only N? does not require a conversation UUID or a Core order write");
 assert.equal(renders.length,1,"the N? card moves immediately in the visible node list");
 assert.equal(renders[0].find(node=>node.selectionKey==="pending-tab").displayOrder,1);
}
async function crossScopeMove(destinationGroupKey, destinationScopeName, expectedScopeName, sourceRoleTags=["Worker","Review"], expectedRoleTags=sourceRoleTags) {
 const updates=[],reorders=[],statuses=[];
 const ctx={
  monitorBctNodeReorderPending:false,monitorBctDraggedNodeKey:"A",
  monitorBctWindowNodesCache:[
   {conversationKey:"A",title:"Worker A",scopeId:"team-a",scopeName:"Team A",roleTags:sourceRoleTags},
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
  monitorBctNodeRoleRank:(node)=>node.roleTags?.includes("Manager")?1:2,
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
 assert.deepEqual(updates[0].values.roleTags,expectedRoleTags,"ordinary roles survive, but scope-bound coordinator roles are released");
 assert.equal(ctx.refreshed,1,"scope changes re-read authoritative Monitor state");
 assert.equal(statuses.length,1);
}
(async()=>{
 await scenario(false);
 await scenario(true);
 await successfulSave();
 await pinnedCoordinatorWorkerReorder();
 await uuidlessPlaceholderDoesNotRejectDurableReorder();
 await uuidlessNodeCanReorderInsideItsCurrentList();
 await crossScopeMove("__unassigned__","","");
 await crossScopeMove("team-b","Team B","Team B");
 await crossScopeMove("__unassigned__","","",["Worker","Manager"],["Worker"]);
 assert.match(source,/monitorBctPointerDrag \|\| monitorBctNodeReorderPending\) return/);
 console.log(JSON.stringify({status:"PASS",cases:9,coverage:"save-failure-rollback,refresh-generation-guard,serial-save-success,pinned-coordinator-worker-reorder,uuidless-placeholder-exclusion,uuidless-node-local-reorder,scope-move-to-unassigned,scope-move-to-network,scope-move-releases-manager"}));
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
