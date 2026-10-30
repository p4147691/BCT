"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null,Map,Set,Array,Object,String,Promise};
ctx.globalThis=ctx;vm.createContext(ctx);
const src=fs.readFileSync(path.join(root,"extension/monitor-diagnostics-command-view.js"),"utf8");
const part=fs.readFileSync(path.join(root,"source-parts/08-desktop-thumbnails.js"),"utf8");
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
vm.runInContext(src,ctx);
assert(html.indexOf('src="monitor-diagnostics-command-view.js"')<html.indexOf('src="monitor.js"'));
assert.match(part,/MonitorDiagnosticsCommandView[.]create/);
assert.doesNotMatch(src,/chrome[.]|child_process|powershell|monitorNative|actFetch|execSync/);
function node(tag){
 const obj={tag,children:[],listeners:new Map(),dataset:{},className:"",disabled:false,
   append(...args){this.children.push(...args)},replaceChildren(...args){this.children=[...args]},
   addEventListener(key,handler){this.listeners.set(key,handler)}};
 return obj;
}
const doc={createElement:node},id="diagnostic.inspect",toolId="bct.mock",capability="inspect";
const emptyHost=node("div"),empty=ctx.MonitorDiagnosticsCommandView.create({host:emptyHost,document:doc});
empty.render();
assert.equal(emptyHost.children[0].textContent,"승인된 진단 명령 미연결");
empty.setCommands([{id,label:"Inspect",toolId,capability}]);
assert.equal(emptyHost.children[0].children[0].disabled,true);
const exact={workId:"w-1",operationId:"op-1",requestHash:"a".repeat(64)};
const effects=[];
let fail=false;
const host=node("div");
const view=ctx.MonitorDiagnosticsCommandView.create({host,document:doc,
  prepare:async()=>({context:exact,payload:{probe:true}}),
  run:async(cmd,context,payload)=>{
    effects.push([cmd.id,context.operationId,payload]);
    if(fail)throw Error("lost");
    return {schema:"monitor.tool.operation.v1",toolId:cmd.toolId,capability:cmd.capability,
      workId:context.workId,operationId:context.operationId,requestHash:context.requestHash,
      outcome:"APPLIED",receipt:{}};},
  reconcile:async(cmd,proof)=>({schema:"monitor.tool.reconciliation.v1",
    toolId:cmd.toolId,workId:exact.workId,operationId:exact.operationId,
    requestHash:proof.badHash?"b".repeat(64):exact.requestHash,
    outcome:"NOT_APPLIED"})
});
(async()=>{
 view.setCommands([{id,label:"Inspect",toolId,capability}]);
 assert.equal(host.children[0].children[0].disabled,false);
 const initial=await view.request(id,exact,{probe:true});
 assert.equal(initial.outcome,"APPLIED");
 assert.equal(view.snapshot(id).outcome,"APPLIED");
 fail=true;
 const lost=await view.request(id,exact,{probe:true});
 assert.equal(lost.outcome,"UNKNOWN");
 assert.equal(host.children[0].children[0].disabled,true);
 await assert.rejects(()=>view.request(id,exact,{}),/UNKNOWN_RECONCILIATION_REQUIRED/);
 await assert.rejects(()=>view.resolveUnknown(id,{badHash:true}),/RECONCILIATION_UNVERIFIED/);
 assert.equal(view.snapshot(id).outcome,"UNKNOWN");
 assert.equal(await view.resolveUnknown(id,{badHash:false}),"NOT_APPLIED");
 assert.equal(view.snapshot(id).outcome,"NOT_APPLIED");
 fail=false;
 host.children[0].children[0].listeners.get("click")();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(view.snapshot(id).outcome,"APPLIED");
 assert.equal(effects.length,3);
 assert.throws(()=>view.setCommands([{id:"?",toolId,capability}]),/INVALID_COMMAND_CONTRACT/);
 console.log("PASS: diagnostic command UI disabled by default, exact injected receipt, UNKNOWN fence and verified reconciliation");
})().catch(e=>{console.error(e);process.exitCode=1});
