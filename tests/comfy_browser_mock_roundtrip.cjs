"use strict";
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const root=path.join(__dirname,"../modules/browser-bridge/comfy-canvas");
const url="http://127.0.0.1:8188/";
const listeners=new Map(),chromeListeners=[];
class CustomEvent{constructor(type,options){this.type=type;this.detail=options?.detail}}
const window={app:{graph:{serialize:()=>({nodes:[{id:42,type:"CLIPTextEncode",widgets_values:["untouched prompt"]}],links:[]})}},addEventListener:(name,fn)=>listeners.set(name,[...(listeners.get(name)||[]),fn]),dispatchEvent:e=>(listeners.get(e.type)||[]).forEach(fn=>fn(e))};
const crypto={randomUUID:()=>"d".repeat(32)};
const chrome={runtime:{id:"bct-comfy-test",onMessage:{addListener:f=>chromeListeners.push(f)}}};
const context={window,location:{origin:url.slice(0,-1),href:url},crypto,chrome,CustomEvent,structuredClone,setTimeout,clearTimeout};
vm.createContext(context);
for(const file of ["comfy-main.js","comfy-isolated.js"]){vm.runInContext(fs.readFileSync(path.join(root,file),"utf8"),context)}
const message={type:"BCT_COMFY_READ_V1",requestId:"a".repeat(32),tabId:123,url,sessionId:"session1"};
let result=null;
chromeListeners[0](message,{id:"bct-comfy-test"},value=>result=value);
if(!result||!result.ok||result.graph.nodes[0].id!==42)process.exit(1);
process.stdout.write(JSON.stringify({tab_id:result.tab_id,url:result.url,session_id:result.session_id,source:"live_canvas_memory",graph:result.graph}));
