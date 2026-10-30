"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const root=path.join(__dirname,"../modules/browser-bridge");
const url="http://127.0.0.1:8188/", id="a".repeat(32);
let nativeHandler=null,nativeDisconnect=null;const sends=[];
const port={onMessage:{addListener:f=>nativeHandler=f},onDisconnect:{addListener:f=>nativeDisconnect=f},postMessage:m=>sends.push(m)};
const runtimeListeners=[];
const chrome={runtime:{id:"authorized-bct",connectNative:()=>port,onMessage:{addListener:f=>runtimeListeners.push(f)}},
 tabs:{get:async tabId=>({id:tabId,url}),sendMessage:async(tabId,m)=>({
    ok:true,requestId:m.requestId,tab_id:tabId,url:m.url,session_id:m.sessionId,
    graph:{nodes:[{id:42,type:"CLIPTextEncode",widgets_values:["demo"]}],links:[]}
 })}};
const scope={self:{},chrome,crypto:{randomUUID:()=>id},Promise,Set,Map,Object};
vm.createContext(scope);
scope.importScripts=(...files)=>files.forEach(file=>{
 const candidate=path.join(root,"extension",file);
 const full=fs.existsSync(candidate)?candidate:path.join(root,file);
 vm.runInContext(fs.readFileSync(full,"utf8"),scope,{filename:file});
});
const entry=fs.readFileSync(path.join(root,"extension","background.js"),"utf8");
vm.runInContext(entry,scope,{filename:"background.js"});
assert.equal(runtimeListeners.length,1);
runtimeListeners[0]({type:"READ_FIXTURE",path:"test"}, {id:"authorized-bct"},()=>{});
assert.ok(nativeHandler);
const cmd={type:"core_comfy_read_command",request_id:id,operation_id:id,generation:1,
 session_id:"host-session",arguments:{tab_id:123,url,session_id:"comfy-session"}};
nativeHandler(cmd);
setImmediate(()=>{
 assert.equal(sends.length,2);
 assert.equal(sends[1].type,"comfy_canvas_result");
 assert.equal(sends[1].request_id,id);
 assert.equal(sends[1].generation,1);
 assert.equal(sends[1].response.graph.nodes[0].id,42);
 nativeHandler(cmd);
 setImmediate(()=>{
  assert.equal(sends.length,2);
  console.log("COMFY_NATIVE_REVERSE_MOCK_PASS");
 });
});
