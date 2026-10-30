"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null};ctx.globalThis=ctx;
vm.createContext(ctx);
const src=fs.readFileSync(path.join(root,"extension/monitor-recovery-picker-state.js"),"utf8");
vm.runInContext(src,ctx);
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
assert(html.indexOf('src="monitor-recovery-picker-state.js"')<html.indexOf('src="monitor.js"'));
for(const file of ["domains/conversations.js","domains/desktop-lifecycle.js","source-parts/03-node-activity.js","source-parts/04-worker-list.js"]) {
  const text=fs.readFileSync(path.join(root,file),"utf8");
  assert.doesNotMatch(text,/monitorClosedConversationPickerOpen/);
}
const a=ctx.MonitorRecoveryPickerState.create();
assert.equal(a.isOpen(),false);
assert.equal(a.toggle(),true);
assert.equal(a.isOpen(),true);
assert.equal(a.show(),true);
assert.equal(a.close(),false);
assert.equal(a.toggle(),true);
assert.equal(a.toggle(),false);
assert.equal(ctx.MonitorRecoveryPickerState.create().isOpen(),false);
console.log("PASS: single Recovery picker visibility owner with isolated toggle/close lifecycle");
