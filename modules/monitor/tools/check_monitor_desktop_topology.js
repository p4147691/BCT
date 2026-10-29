"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null,Array,Number,String,Math,Object,Boolean};
ctx.globalThis=ctx;vm.createContext(ctx);
const src=fs.readFileSync(path.join(root,"extension/monitor-desktop-topology.js"),"utf8");
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
const domain=fs.readFileSync(path.join(root,"domains/desktop-lifecycle.js"),"utf8");
vm.runInContext(src,ctx);
assert(html.indexOf('src="monitor-desktop-topology.js"')<html.indexOf('src="monitor.js"'));
assert.match(domain,/MonitorDesktopTopology[.]project/);
assert.doesNotMatch(src,/chrome[.]|monitorNative|document[.]|actFetch/);
const project=ctx.MonitorDesktopTopology.project;
const ids=["guid-D1","guid-D2"];
const current=project({observed:{count:2,currentIndex:0,desktopIds:ids,hostDesktopId:"guid-D1",hostWindowHwnd:"100"},
  previous:{},sharedSelection:{ready:false}});
assert.equal(current.state.currentDesktopId,"guid-D1");
assert.equal(current.state.hostDesktopId,"guid-D1");
assert.equal(current.state.selectedIndex,0);
assert.equal(current.hostWindowChanged,true);
const observed=project({observed:{desktopIds:ids,count:2,currentIndex:0,hostWindowHwnd:"100"},
  previous:current.state,sharedSelection:{ready:true,desktopId:"guid-D2"}});
assert.equal(observed.state.currentDesktopId,"guid-D1");
assert.equal(observed.state.observedDesktopId,"guid-D2");
assert.equal(observed.state.selectedIndex,1);
assert.equal(observed.state.hostDesktopId,"guid-D1");
assert.equal(observed.hostWindowChanged,false);
const moved=project({observed:{desktopIds:ids,count:2,currentIndex:1,hostWindowAmbiguous:true},
  previous:observed.state,sharedSelection:{ready:true,desktopId:"not-real"}});
assert.equal(moved.state.currentDesktopId,"guid-D2");
assert.equal(moved.state.hostDesktopId,null);
assert.equal(moved.state.hostWindowHwnd,null);
assert.equal(moved.hostWindowChanged,true);
assert.equal(moved.state.observedDesktopId,"guid-D2");
const unknown=project({observed:{desktopIds:[],count:0,currentIndex:-2,hostWindowHwnd:"0"},
  previous:{},sharedSelection:{ready:true,desktopId:"fake"}});
assert.equal(unknown.state.count,1);
assert.equal(unknown.state.selectedIndex,0);
assert.equal(unknown.state.currentDesktopId,null);
assert.equal(unknown.state.hostWindowHwnd,null);
assert.equal(current.state.desktopIds,ids,"single observed GUID array must remain source");
console.log("PASS: desktop topology GUID authority, host ambiguity, shared D1/D2 preview and exact HWND");
