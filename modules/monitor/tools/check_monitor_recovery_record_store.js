"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null};ctx.globalThis=ctx;vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(root,"extension/monitor-recovery-record-store.js"),"utf8"),ctx);
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
assert(html.indexOf('src="monitor-recovery-record-store.js"')<html.indexOf('src="monitor.js"'));
const store=ctx.MonitorRecoveryRecordStore.create();
const {ghosts,trash,trashedKeys}=store;
assert(Object.isFrozen(store));assert(Object.isFrozen(ghosts));assert(Object.isFrozen(trash));assert(Object.isFrozen(trashedKeys));
assert.equal(ghosts.size,0);ghosts.set("uuid1",{title:"A"});
assert.equal(ghosts.get("uuid1").title,"A");assert.equal(ghosts.has("uuid1"),true);
assert.equal([...ghosts].length,1);assert.equal([...ghosts.values()].length,1);
trash.set("uuid1",{trash_source:"list"});
assert.equal(trash.get("uuid1").trash_source,"list");
assert.equal([...trash][0][0],"uuid1");
trashedKeys.add("uuid1");assert.equal(trashedKeys.has("uuid1"),true);
assert.equal([...trashedKeys][0],"uuid1");assert.equal(trashedKeys.size,1);
assert.equal(trashedKeys.delete("uuid1"),true);
assert.equal(ghosts.delete("uuid1"),true);assert.equal(ghosts.size,0);
assert.equal(ctx.MonitorRecoveryRecordStore.create().trash.size,0);
for(const folder of ["domains","source-parts"])for(const file of fs.readdirSync(path.join(root,folder)).filter(n=>n.endsWith(".js"))) {
 const s=fs.readFileSync(path.join(root,folder,file),"utf8");
 assert.doesNotMatch(s,/\b(?:monitorGhostCache|monitorTrashRecords|monitorTrashedConversationKeys)\b/,
   "Recovery collections may not be direct lexical globals: "+file);
}
console.log("PASS: private Recovery Map/Set owners, exact UUID contract, iteration, mutation methods, no cross-domain globals");
