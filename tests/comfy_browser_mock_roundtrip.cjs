"use strict";
// Entire isolated worker -> content isolated -> page MAIN fixed read transport.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const root=path.join(__dirname,"../modules/browser-bridge/comfy-canvas");
const url="http://127.0.0.1:8188/", tabId=123, sessionId="session1", requestId="a".repeat(32);
const listeners=new Map(),contentListeners=[],workerListeners=[];
class CustomEvent {constructor(type,options){this.type=type;this.detail=options?.detail}}
const window={app:{graph:{serialize:()=>({nodes:[{id:42,type:"CLIPTextEncode",widgets_values:["untouched prompt"]}],links:[]})}},
 addEventListener:(name,fn)=>listeners.set(name,[...(listeners.get(name)||[]),fn]),
 dispatchEvent:e=>(listeners.get(e.type)||[]).forEach(fn=>fn(e))};
const chrome={runtime:{id:"bct-comfy-test",onMessage:{addListener:f=>contentListeners.push(f)}}};
const content={window,location:{origin:url.slice(0,-1),href:url},crypto:{randomUUID:()=>"d".repeat(32)},
 chrome,CustomEvent,structuredClone,setTimeout,clearTimeout};
vm.createContext(content);
for(const file of ["comfy-main.js","comfy-isolated.js"])
 vm.runInContext(fs.readFileSync(path.join(root,file),"utf8"),content,{filename:file});
const tabApi={tabs:{
 get:async id=>{if(id!==tabId)throw Error("TAB_NOT_FOUND");return {id,url}},
 sendMessage:async(id,message)=>new Promise((resolve,reject)=>{
   if(id!==tabId)return reject(Error("WRONG_TAB"));
   if(contentListeners.length!==1)return reject(Error("CONTENT_NOT_READY"));
   contentListeners[0](message,{id:"bct-comfy-test"},resolve);
 })}};
const workChrome={...tabApi,runtime:{id:"bct-comfy-test",onMessage:{addListener:f=>workerListeners.push(f)}}};
const worker={self:{},chrome:workChrome,setTimeout,clearTimeout,Promise,Error,Set,Object};
vm.createContext(worker);
worker.importScripts=(...names)=>names.forEach(name=>vm.runInContext(
 fs.readFileSync(path.join(root,name),"utf8"),worker,{filename:name}));
vm.runInContext(fs.readFileSync(path.join(root,"comfy-worker.js"),"utf8"),worker);
(async()=>{
 if(workerListeners.length!==1)throw Error("WORKER_NOT_READY");
 const response=await new Promise(resolve=>workerListeners[0]({
   type:"BCT_COMFY_READ_COMMAND_V1",requestId,tabId,url,sessionId
 },{id:"bct-comfy-test"},resolve));
 if(!response?.ok||response.requestId!==requestId||response.tab_id!==tabId
   ||response.url!==url||response.session_id!==sessionId)throw Error("ROUNDTRIP_INVALID");
 if(response.graph?.nodes?.[0]?.id!==42)throw Error("GRAPH_INVALID");
 process.stdout.write(JSON.stringify({ok:response.ok,requestId:response.requestId,tab_id:response.tab_id,url:response.url,
  session_id:response.session_id,source:"live_canvas_memory",graph:response.graph}));
})().catch(e=>{console.error(e);process.exitCode=1});
