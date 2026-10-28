"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null,Map,Set,Array,String,Number,Object};
ctx.globalThis=ctx;vm.createContext(ctx);
const source=fs.readFileSync(path.join(root,"extension/monitor-recovery-inventory.js"),"utf8");
vm.runInContext(source,ctx);
const domain=fs.readFileSync(path.join(root,"domains/desktop-lifecycle.js"),"utf8");
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
assert(html.indexOf('src="monitor-recovery-inventory.js"')<html.indexOf('src="monitor.js"'));
assert.match(domain,/monitorRecoveryInventoryController[.]project/);
const controller=ctx.MonitorRecoveryInventory.create({toEpoch:value=>Number(value)||0});
const ghosts=[{conversation_key:"old",open:false,closed_at_ms:80},
  {conversation_key:"trashed",open:false},{conversation_key:"open-ghost",open:true}];
const snapshot={captured_at_ms:70,items:[
  {conversation_key:"reboot-2",desktop:2,slot:1,closed_at_ms:60},
  {conversation_key:"reboot-1",desktop:1,slot:3,closed_at_ms:20},
  {conversation_key:"open-current",desktop:3},
  {conversation_key:"trashed",desktop:4},
  {conversation_key:"",desktop:5}
]};
const first=controller.project({ghosts,snapshot,trashedKeys:new Set(["trashed"]),
  endpoints:[{conversation_key:"open-current",presence_state:"OPEN"},
    {conversation_key:"reboot-1",first_seen_at:50,closed_at:90}]});
const keys=Array.from(first.items,x=>x.conversation_key);
assert.deepEqual(keys,["reboot-1","reboot-2","old"]);
assert.equal(first.changed,true);
assert.equal(first.updatedSnapshot.items[1].first_seen_ms,50);
assert.equal(first.updatedSnapshot.items[1].closed_at_ms,90);
assert.equal(snapshot.items[1].closed_at_ms,20,"input snapshot must remain untouched");
const again=controller.project({ghosts,snapshot:first.updatedSnapshot,trashedKeys:new Set(["trashed"]),
  endpoints:[{conversation_key:"open-current",presence_state:"OPEN"},
    {conversation_key:"reboot-1",first_seen_at:50,closed_at:90}]});
assert.equal(again.changed,false);
assert.equal(again.updatedSnapshot,null);
const noEvidence=controller.project({ghosts,snapshot:{items:[]},endpoints:[]});
assert.deepEqual(Array.from(noEvidence.items,x=>x.conversation_key),["old","trashed"]);
assert.throws(()=>ctx.MonitorRecoveryInventory.create(),/EPOCH/);
assert.doesNotMatch(source,/chrome[.]|monitorNative|actFetch|document[.]/);
console.log("PASS: recovery inventory closed/reboot filtering, exact conversation keys, ordering and snapshot reconciliation");
