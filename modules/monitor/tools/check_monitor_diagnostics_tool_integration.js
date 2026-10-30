"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null,Map,Set,Object,String,Array,Promise};
ctx.globalThis=ctx;vm.createContext(ctx);
for(const name of ["monitor-tool-connector-registry.js","monitor-diagnostics-tool-port.js","monitor-diagnostics-command-view.js"])
  vm.runInContext(fs.readFileSync(path.join(root,"extension",name),"utf8"),ctx);
const hash="e".repeat(64);
const context=id=>({workId:"work-verified",operationId:id,requestHash:hash});
const confirm=exact=>({ok:true,...exact});
let requests=0,denials=0,uncertain=false;
const registry=ctx.MonitorToolConnectorRegistry.create({
 authorize:async exact=>{
  if(exact.operationId==="denied"){denials++;return {ok:false};}
  return confirm(exact);
 },
 verifyReceipt:async ({original,toolId,proof})=>({
  ok:proof?.verified===true,final:true,toolId,
  workId:original.workId,operationId:original.operationId,requestHash:original.requestHash,
  outcome:"NOT_APPLIED",receipt:{reconciled:true}
 })
});
registry.register({
 id:"mock.native",capabilities:["inspect"],
 connect:async({context:x})=>({...x,outcome:"APPLIED"}),
 disconnect:async({context:x})=>({...x,outcome:"APPLIED"}),
 status:async({context:x})=>({...x,outcome:"APPLIED"}),
 request:async({context:x,payload})=>{
   requests++;
   if(uncertain)throw Error("unknown reply");
   return {...x,outcome:"APPLIED",receipt:{command:payload.test}};
 }
});
function el(tag) {
 const x={tag,children:[],disabled:false,listeners:new Map(),dataset:{},
 replaceChildren(...items){this.children=[...items]},
 append(...items){this.children.push(...items)},
 addEventListener(k,f){this.listeners.set(k,f)}};return x;
}
const host=el("div"),doc={createElement:el};
let currentOperation="req1",approvedPrepare=true;
const port=ctx.MonitorDiagnosticsToolPort.create({
 registry,prepare:async command=>{
  if(!approvedPrepare)throw Error("no user approval");
  assert.equal(command.toolId,"mock.native");
  return {context:context(currentOperation),payload:{test:"exact"}};
 }
});
const view=ctx.MonitorDiagnosticsCommandView.create({host,document:doc,...port});
async function run(){
 await registry.connect("mock.native",context("connect1"));
 view.setCommands([{id:"diag.inspect",label:"Inspect",toolId:"mock.native",capability:"inspect"}]);
 assert.equal(host.children[0].children[0].disabled,false);
 const direct=await view.request("diag.inspect",context("req1"),{test:"exact"});
 assert.equal(direct.outcome,"APPLIED");
 assert.equal(requests,1);
 currentOperation="req2";host.children[0].children[0].listeners.get("click")();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(requests,2);
 assert.equal(view.snapshot("diag.inspect").outcome,"APPLIED");
 approvedPrepare=false;currentOperation="denied";
 host.children[0].children[0].listeners.get("click")();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(view.snapshot("diag.inspect").outcome,"NOT_APPLIED");
 assert.equal(requests,2,"failed prepare must never send");
 approvedPrepare=true;
 const denied=await view.request("diag.inspect",context("denied"),{test:"exact"});
 assert.equal(denied.outcome,"NOT_APPLIED");
 assert.equal(denials,1);
 assert.equal(requests,2);
 uncertain=true;
 const u=await view.request("diag.inspect",context("uncertain-1"),{test:"exact"});
 assert.equal(u.outcome,"UNKNOWN");
 assert.equal(registry.snapshot("mock.native").needsReconciliation,true);
 await assert.rejects(()=>view.request("diag.inspect",context("uncertain-2"),{}),/UNKNOWN_RECONCILIATION_REQUIRED/);
 await assert.rejects(()=>view.resolveUnknown("diag.inspect",{verified:false}),/EXACT_RECEIPT_NOT_VERIFIED/);
 assert.equal(view.snapshot("diag.inspect").outcome,"UNKNOWN");
 assert.equal(await view.resolveUnknown("diag.inspect",{verified:true}),"NOT_APPLIED");
 assert.equal(registry.snapshot("mock.native").needsReconciliation,false);
 uncertain=false;
 const fixed=await view.request("diag.inspect",context("after-reconcile"),{test:"exact"});
 assert.equal(fixed.outcome,"APPLIED");
 assert.equal(requests,4);
 const hostHtml=fs.readFileSync(path.join(root,"extension","desktop.html"),"utf8");
 assert(hostHtml.includes('src="monitor-diagnostics-tool-port.js"'));
 console.log("PASS: full diagnostics UI ↔ tool registry, exact context, approval denial, UNKNOWN and reconciliation");
}
run().catch(e=>{console.error(e);process.exitCode=1});
