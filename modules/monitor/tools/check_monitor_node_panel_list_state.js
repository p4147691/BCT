"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null};ctx.globalThis=ctx;vm.createContext(ctx);
const script=fs.readFileSync(path.join(root,"extension/monitor-node-panel-list-state.js"),"utf8");
vm.runInContext(script,ctx);
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
assert(html.indexOf('src="monitor-node-panel-list-state.js"')<html.indexOf('src="monitor.js"'));
const state=ctx.MonitorNodePanelListState.create();
assert.equal(state.snapshot(),null);
const a=[{conversationKey:"UUID-A",tabId:100}];
state.replace(a);
assert.equal(state.snapshot(),a,"optimistic rollback compares original array identity");
const previous=state.snapshot().slice();
const optimistic=[{conversationKey:"UUID-B",tabId:200}];
state.replace(optimistic);
assert.equal(state.snapshot(),optimistic);
const later=[{conversationKey:"UUID-C"}];
state.replace(later);
assert.equal(state.rollbackIfCurrent(optimistic,previous),false);
assert.equal(state.snapshot(),later,"newer RCC refresh must survive stale rollback");
assert.equal(state.rollbackIfCurrent(later,previous),true);
assert.equal(state.snapshot(),previous);
assert.equal(state.revision(),4);
assert.throws(()=>state.replace({invalid:1}),/NODE_PANEL_LIST_INVALID/);
for(const folder of ["domains","source-parts"])for(const file of fs.readdirSync(path.join(root,folder)).filter(n=>n.endsWith(".js"))){
 const src=fs.readFileSync(path.join(root,folder,file),"utf8");
 assert.doesNotMatch(src,/\bmonitorBctWindowNodesCache\b/,
   "all consumers use the NodePanel list owner: "+file);
}
console.log("PASS: RCC NodePanel sole observed list authority, exact identity and stale drag rollback fence");
