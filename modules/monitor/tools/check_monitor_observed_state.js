"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null};ctx.globalThis=ctx;vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(root,"extension/monitor-observed-state.js"),"utf8"),ctx);
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
assert(html.indexOf('src="monitor-observed-state.js"')<html.indexOf('src="monitor.js"'));
const api=ctx.MonitorObservedState.create(),old={endpoints:[{conversation_key:"first"}],state_id:1},newer={state_id:2};
assert.equal(api.snapshot(),null);
api.replace(old);assert.equal(api.snapshot(),old);
api.replace(newer);assert.equal(api.snapshot(),newer);
assert.equal(api.revision(),2);
for(const folder of ["domains","source-parts"])for(const file of fs.readdirSync(path.join(root,folder)).filter(n=>n.endsWith(".js"))){
 const source=fs.readFileSync(path.join(root,folder,file),"utf8");
 assert.doesNotMatch(source,/\bmonitorLastAiState\b/,
  "Observed ACT state may not be a shared lexical variable: "+file);
}
console.log("PASS: app-level ACT/BCT observation owner, exact state reference, no lexical global reads or writes");
