"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const file = path.join(root, "extension/monitor-tool-connector-registry.js");
const source = fs.readFileSync(file,"utf8");
const html = fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
const sandbox = {globalThis:null,Map,Set,Object,String,Array,Promise};
sandbox.globalThis=sandbox;
vm.createContext(sandbox);
vm.runInContext(source,sandbox,{filename:file});
const create=sandbox.MonitorToolConnectorRegistry.create;
const hash = "a".repeat(64);
const context = (operationId, overrides={}) =>
  ({workId:"monitor-contract-test",operationId,requestHash:hash,...overrides});
const approved = exact => ({ok:true,workId:exact.workId,operationId:exact.operationId,
  requestHash:exact.requestHash,action:exact.action,capability:exact.capability,toolId:exact.toolId});
async function run() {
  const calls=[], events=[];
  const gateway=create({
    authorize:async exact=>exact.operationId==="denied" ? {ok:false}:approved(exact),
    onChange:event=>events.push({state:event.snapshot?.state,toolId:event.toolId})
  });
  const adapter = {
    id:"mock.desktop",capabilities:["inspect","move"],
    connect:async ({context:x})=>({outcome:"APPLIED",...x,receipt:{connection:"test"}}),
    disconnect:async ({context:x})=>({outcome:"APPLIED",...x}),
    status:async ({context:x})=>({outcome:"APPLIED",...x,receipt:{health:"OK"}}),
    request:async ({capability,payload,context:x}) => {
      calls.push({capability,payload});
      return {outcome:"APPLIED",...x,receipt:{observed:true}};
    }
  };
  assert.throws(()=>gateway.register({id:"bad",capabilities:["x"]}),/INVALID_TOOL_PORTS/);
  gateway.register(adapter);
  assert.equal(gateway.snapshot("mock.desktop").state,"DISCONNECTED");
  await assert.rejects(()=>gateway.request("mock.desktop","inspect",{},context("not-connected")),/TOOL_DISCONNECTED/);
  const denied=await gateway.connect("mock.desktop",context("denied"));
  assert.equal(denied.outcome,"NOT_APPLIED");
  assert.equal(gateway.snapshot("mock.desktop").connected,false);
  const connected=await gateway.connect("mock.desktop",context("connect"));
  assert.equal(connected.outcome,"APPLIED");
  const healthy=await gateway.status("mock.desktop",context("status"));
  assert.equal(healthy.receipt.health,"OK");
  const request=await gateway.request("mock.desktop","inspect",{id:"D1"},context("inspect"));
  assert.equal(request.outcome,"APPLIED");
  assert.equal(calls.length,1);
  const duplicate=await gateway.request("mock.desktop","inspect",{id:"D1"},context("inspect"));
  assert.equal(duplicate,request);
  assert.equal(calls.length,1);
  await assert.rejects(()=>gateway.request("mock.desktop","inspect",{id:"D9"},context("inspect")),/OPERATION_ID_REUSE_MISMATCH/);
  await assert.rejects(()=>gateway.request("mock.desktop","move",{},context("inspect")),/OPERATION_ID_REUSE_MISMATCH/);
  await assert.rejects(()=>gateway.request("mock.desktop","delete",{},context("invalid")),/UNSUPPORTED_CAPABILITY/);
  const disconnected=await gateway.disconnect("mock.desktop",context("disconnect"));
  assert.equal(disconnected.outcome,"APPLIED");
  assert.equal(gateway.snapshot("mock.desktop").connected,false);
  assert.equal(await gateway.unregister("mock.desktop"),true);
  assert.equal(gateway.list().length,0);
  assert(events.some(x=>x.state===undefined));

  let uncertainRuns=0;
  const g2=create({authorize:async exact=>approved(exact),
    verifyReceipt:async ({toolId,original,proof})=>({
      ok:proof?.approved===true,final:true,toolId,workId:original.workId,
      operationId:original.operationId,requestHash:original.requestHash,outcome:"NOT_APPLIED",
      receipt:{source:"verified BCT operation"}
    })
  });
  g2.register({...adapter,id:"mock.unknown",request:async()=>{uncertainRuns++;throw Error("connection lost");}});
  await g2.connect("mock.unknown",context("c2"));
  const unknown=await g2.request("mock.unknown","move",{target:"D2"},context("u2"));
  assert.equal(unknown.outcome,"UNKNOWN");
  assert.equal(g2.snapshot("mock.unknown").needsReconciliation,true);
  assert.equal((await g2.status("mock.unknown",context("status2"))).outcome,"APPLIED");
  assert.equal(g2.snapshot("mock.unknown").state,"UNKNOWN");
  await assert.rejects(()=>g2.request("mock.unknown","move",{target:"D2"},context("u3")),/UNKNOWN_RECONCILIATION_REQUIRED/);
  await assert.rejects(()=>g2.disconnect("mock.unknown",context("d2")),/UNKNOWN_RECONCILIATION_REQUIRED/);
  assert.equal((await g2.request("mock.unknown","move",{target:"D2"},context("u2"))).outcome,"UNKNOWN");
  assert.equal(uncertainRuns,1);
  await assert.rejects(()=>g2.reconcile("mock.unknown",{approved:false}),/EXACT_RECEIPT_NOT_VERIFIED/);
  assert.equal(g2.snapshot("mock.unknown").needsReconciliation,true);
  const reconciled=await g2.reconcile("mock.unknown",{approved:true});
  assert.equal(reconciled.outcome,"NOT_APPLIED");
  assert.equal(g2.snapshot("mock.unknown").needsReconciliation,false);
  assert.equal(g2.snapshot("mock.unknown").state,"CONNECTED");
  await assert.rejects(()=>g2.request("mock.unknown","move",{target:"D2"},context("u2", {requestHash:"b".repeat(64)})),/OPERATION_ID_REUSE_MISMATCH/);

  assert.doesNotMatch(source,/chrome[.]|child_process|powershell|execSync|connectNative/);
  assert(html.includes('src="monitor-tool-connector-registry.js"'),"tool registry must be in the composition load graph");
  console.log("PASS: external-tool registry with exact Work/Operation, denial, idempotence, UNKNOWN hold, lifecycle and no direct effects");
}
run().catch(err=>{console.error(err);process.exitCode=1;});
