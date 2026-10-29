"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const root=path.join(__dirname,"../modules/browser-bridge/comfy-canvas");
const handlers=new Map();
class CustomEvent{constructor(type,options){this.type=type;this.detail=options?.detail}}
const window={app:{graph:{serialize:()=>({nodes:[{id:1,type:"CLIPTextEncode",widgets_values:["hello"]}],links:[]})}},addEventListener:(name,cb)=>{const all=handlers.get(name)||[];all.push(cb);handlers.set(name,all)},dispatchEvent:(e)=>{for(const fn of handlers.get(e.type)||[])fn(e)}};
const listeners=[];
const chrome={runtime:{id:"ext1",onMessage:{addListener:cb=>listeners.push(cb)}}};
let count=0;
const crypto={randomUUID:()=>("a".repeat(32))};
const ctx={window,location:{origin:"http://127.0.0.1:8188",href:"http://127.0.0.1:8188/"},chrome,CustomEvent,structuredClone,crypto,setTimeout,clearTimeout};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(root,"comfy-main.js"),"utf8"),ctx);
vm.runInContext(fs.readFileSync(path.join(root,"comfy-isolated.js"),"utf8"),ctx);
function send(msg){let result;const async= listeners[0](msg,{id:"ext1"},r=>{count++;result=r});return {async,result}}
const msg={type:"BCT_COMFY_READ_V1",requestId:"b".repeat(32),tabId:123,url:"http://127.0.0.1:8188/",sessionId:"session"};
const first=send(msg);
assert.equal(first.async,true);assert.equal(first.result.ok,true);assert.equal(first.result.requestId,msg.requestId);
assert.equal(first.result.graph.nodes.length,1);
assert.equal(send(msg).result.error,"COMFY_IDENTITY_INVALID");
assert.equal(send({...msg,requestId:"c".repeat(32),url:"http://evil.test/"}).result.error,"COMFY_IDENTITY_INVALID");
assert.equal(send({...msg,requestId:"d".repeat(32),sessionId:""}).result.error,"COMFY_IDENTITY_INVALID");
assert.equal(count,4);
console.log("COMFY_MAIN_ISOLATED_MOCK_5_PASS");
