"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null};ctx.globalThis=ctx;vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(root,"extension/monitor-recovery-snapshot-state.js"),"utf8"),ctx);
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
assert(html.indexOf('src="monitor-recovery-snapshot-state.js"')<html.indexOf('src="monitor.js"'));
const store=ctx.MonitorRecoverySnapshotState.create();
const initial=store.snapshot();
assert.equal(initial.captured_at_ms,0);
assert(Object.isFrozen(initial));assert(Object.isFrozen(initial.items));
assert.equal(store.revision(),0);
const raw={captured_at_ms:100,items:[{conversation_key:"uuid-1",closed_at_ms:50}]};
store.replace(raw);
raw.items.push({conversation_key:"unexpected"});
assert.equal(store.snapshot().items.length,1);
assert.equal(store.snapshot().items[0].conversation_key,"uuid-1");
assert.equal(initial.items.length,0);
assert.equal(store.revision(),1);
assert.throws(()=>store.replace(null),/REBOOT_SNAPSHOT_INVALID/);
for(const folder of ["domains","source-parts"])for(const file of fs.readdirSync(path.join(root,folder)).filter(n=>n.endsWith(".js"))){
 const text=fs.readFileSync(path.join(root,folder,file),"utf8");
 assert.doesNotMatch(text,/\bmonitorRebootSnapshot\b/,
   "all reboot snapshot reads/writes must use the sole recovery owner: "+file);
}
console.log("PASS: recovery reboot snapshot single owner, safe array snapshot, no cross-domain global writes");
