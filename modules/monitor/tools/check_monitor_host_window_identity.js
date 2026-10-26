"use strict";
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),assert=require("node:assert/strict");
const root=path.join(__dirname,".."),ext=path.join(root,"extension");
const text=fs.readFileSync(path.join(ext,"monitor-host-window-identity.js"),"utf8");
const html=fs.readFileSync(path.join(ext,"desktop.html"),"utf8");
const generated=fs.readFileSync(path.join(ext,"monitor.js"),"utf8");
const scope={globalThis:null,Array,String,Number,Object,Promise,Error,RegExp};
scope.globalThis=scope;vm.createContext(scope);vm.runInContext(text,scope,{timeout:4000});
const api=scope.MonitorHostWindowIdentity;
assert(Object.isFrozen(api));
assert.equal(typeof api.resolve,"function");
const D1="11111111-1111-4111-8111-111111111111",D2="22222222-2222-4222-8222-222222222222";
const blank={ok:true,currentIndex:1,desktopIds:[D1,D2],hostWindowHwnd:null,hostDesktopId:null,hostWindowAmbiguous:false};
const good={...blank,hostWindowHwnd:"9766666",hostDesktopId:D2,hostWindowTitle:"DesktopWindow Monitor - G1"};
const allowTitle=s=>s.startsWith("DesktopWindow Monitor");
const bounds={left:0,top:569,width:1294,height:703};
(async()=>{
  let calls=[];
  const requestNative=async p=>{
    calls.push(p);
    return p.hostTitle ? blank : good;
  };
  const actual=await api.resolve(blank,{title:"BCT Window Monitor - 2.0.44",bounds,requestNative,isOwnTitle:allowTitle});
  assert.equal(actual.hostWindowHwnd,good.hostWindowHwnd,"exact geometry fallback must recover GUI HWND");
  assert.equal(calls.length,2);
  assert.equal(calls[0].hostTitle,"BCT Window Monitor - 2.0.44");
  assert.equal(calls[1].hostTitle,"");
  assert.equal(calls[1].left,0);assert.equal(calls[1].top,569);assert.equal(calls[1].width,1294);assert.equal(calls[1].height,703);
  calls=[];
  const titleMatched=await api.resolve(blank,{title:"BCT Window Monitor",bounds,requestNative:async q=>{calls.push(q);return good},isOwnTitle:allowTitle});
  assert.equal(titleMatched,good);assert.equal(calls.length,1,"valid title-only path requires no geometry lookup");
  calls=[];
  const already=await api.resolve(good,{title:"ignored",bounds,requestNative:async q=>{calls.push(q)},isOwnTitle:allowTitle});
  assert.equal(already,good);assert.equal(calls.length,0,"previous verified HWND stays unchanged");
  for(const bad of [
    {...good,hostWindowAmbiguous:true},
    {...good,hostWindowHwnd:"0"},
    {...good,hostWindowHwnd:"wrong"},
    {...good,hostWindowTitle:"Unrelated Chrome window"},
    {...good,hostDesktopId:"33333333-3333-4333-8333-333333333333"},
  ]){
    const result=await api.resolve(blank,{title:"BCT Window Monitor",bounds,requestNative:async q=>q.hostTitle?blank:bad,isOwnTitle:allowTitle});
    assert.equal(result,blank,"invalid candidate must fail closed");
  }
  calls=[];
  await api.resolve(blank,{title:"BCT Window Monitor",bounds:{left:0,top:0,width:0,height:0},requestNative:async q=>{calls.push(q);return blank},isOwnTitle:allowTitle});
  assert.equal(calls.length,1,"invalid geometry cannot authorize a fallback");
  assert.equal(html.split('src="monitor-host-window-identity.js"').length,2,"load exactly once");
  assert(html.indexOf('src="monitor-host-window-identity.js"')<html.indexOf('src="monitor.js"'));
  assert(generated.includes("MonitorHostWindowIdentity.resolve(topology"),"generated startup must invoke the new owner after background startup");
  console.log("PASS actual hostTitle-vs-OS-title fallback, strict GUID/HWND/ambiguity constraints, no guessed window, and script order");
})().catch(e=>{console.error(e);process.exitCode=1});
