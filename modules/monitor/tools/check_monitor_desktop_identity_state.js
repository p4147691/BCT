"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null};ctx.globalThis=ctx;
vm.createContext(ctx);
const src=fs.readFileSync(path.join(root,"extension/monitor-desktop-identity-state.js"),"utf8");
vm.runInContext(src,ctx);
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
assert(html.indexOf('src="monitor-desktop-identity-state.js"')<html.indexOf('src="monitor.js"'));
const state=ctx.MonitorDesktopIdentityState.create({
  count:2,currentIndex:0,selectedIndex:0,currentDesktopId:"guid-1",desktopIds:["guid-1","guid-2"]
});
const a=state.snapshot();
assert(Object.isFrozen(a));assert(Object.isFrozen(a.desktopIds));
assert.equal(a.desktopIds.length,2);assert.equal(a.currentDesktopId,"guid-1");
assert.equal(state.snapshot(),a,"unmodified state is stable across reads");
assert.equal(state.revision(),0);
state.patch({observedDesktopId:"guid-2",selectedIndex:1});
const b=state.snapshot();
assert.notEqual(a,b);
assert.equal(b.currentDesktopId,"guid-1");
assert.equal(b.observedDesktopId,"guid-2");
assert.equal(b.selectedIndex,1);
assert.equal(a.selectedIndex,0,"old snapshots are not mutated");
assert.equal(state.revision(),1);
const input={count:1,currentIndex:0,selectedIndex:0,desktopIds:["new-guid"]};
state.replace(input);input.desktopIds.push("injected");
assert.equal(state.snapshot().desktopIds.length,1);
assert.equal(state.revision(),2);
assert.throws(()=>state.patch(null),/DESKTOP_STATE_PATCH_INVALID/);
for (const folder of ["domains","source-parts"]) {
  for (const file of fs.readdirSync(path.join(root,folder)).filter(n=>n.endsWith(".js"))) {
    const text=fs.readFileSync(path.join(root,folder,file),"utf8");
    assert.doesNotMatch(text,/\bmonitorDesktopState\b/,
      "all domains must use the injected canonical desktop identity owner: "+file);
  }
}
console.log("PASS: canonical DesktopStage/Strip identity owner, immutable snapshots, precise mutations and no legacy globals");
