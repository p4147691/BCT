"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const root=path.join(__dirname,"../modules/browser-bridge/comfy-canvas");
const listeners=[];const url="http://127.0.0.1:8188/",id="a".repeat(32);
const chrome={runtime:{id:"ext",onMessage:{addListener:cb=>listeners.push(cb)}},tabs:{get:async()=>({url}),sendMessage:async(tab,m)=>({ok:true,requestId:m.requestId,tab_id:tab,url:m.url,session_id:m.sessionId})}};
const ctx={self:{},chrome,importScripts:(...names)=>names.forEach(n=>vm.runInContext(fs.readFileSync(path.join(root,n),"utf8"),ctx)),setTimeout,clearTimeout,Promise,Error,Object,Set};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,"comfy-worker.js"),"utf8"),ctx);
const call=(m)=>new Promise(resolve=>listeners[0](m,{id:"ext"},resolve));
(async()=>{
const m={type:"BCT_COMFY_READ_COMMAND_V1",requestId:id,tabId:12,url,sessionId:"s1"};
assert.equal((await call(m)).ok,true);
assert.match((await call(m)).error,/DUPLICATE/);
assert.match((await call({...m,requestId:"b".repeat(32),url:"http://evil.test/"})).error,/IDENTITY/);
console.log("COMFY_WORKER_MOCK_3_PASS");
})().catch(e=>{console.error(e);process.exitCode=1});
