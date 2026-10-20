"use strict";
const assert = require("node:assert/strict");
const {test} = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const api = require("../extension/chat_protocol.js");
const url = "https://chatgpt.com/c/6ad733b6-95d4-83ee-b4ba-49a671229d77";
const grantA = "a".repeat(32), grantB = "b".repeat(32);
const marker = '[['+'BCT_LOCAL_READ_REQUEST'+']]\n{"operation":"read","path":"C:\\\\fixture\\\\readme.txt"}\n[[/BCT_LOCAL_READ_REQUEST]]';
const source = fs.readFileSync(path.join(__dirname,"../extension/chat_content.js"),"utf8");

function harness() {
  const state={grant:grantA,nodes:[{innerText:marker}],readCalls:[],clicks:0,
    editor:{innerText:"",focus(){}},store:new Map(),timers:[],listeners:[],statusCalls:0,
    resolveRead:null};
  const document={
    querySelector(s){
      if(s==="main")return {};
      if(s.includes("stop-button"))return null;
      if(s.includes("prompt-textarea"))return state.editor;
      if(s.includes("send-button"))return {disabled:false,click(){state.clicks++}};
      return null;
    },
    querySelectorAll(){return state.nodes},
    execCommand(_a,_b,txt){state.editor.innerText=txt;return true}
  };
  const chrome={
    storage:{local:{
      async get(key){return {[key]:state.store.get(key)}},
      async set(obj){for(const [k,v]of Object.entries(obj))state.store.set(k,v)},
      async remove(key){state.store.delete(key)}
    }},
    runtime:{
      async sendMessage(msg){
        if(msg.type==="BRIDGE_CHAT_STATUS"){
          state.statusCalls++;
          return {enabled:!!state.grant,grantId:state.grant,tabId:101};
        }
        if(msg.type==="BRIDGE_CHAT_READ"){
          state.readCalls.push(msg);
          return new Promise(resolve=>{state.resolveRead=resolve});
        }
        throw Error("UNEXPECTED_MESSAGE:"+msg.type);
      },
      onMessage:{addListener(fn){state.listeners.push(fn)}}
    }
  };
  const timeout=(fn)=>{const task={fn,live:true};state.timers.push(task);return task};
  const clear=(task)=>{if(task)task.live=false};
  vm.runInNewContext(source,{
    BctBridgeChat:api,location:{href:url},document,chrome,
    MutationObserver:class{observe(){}},
    crypto:require("node:crypto").webcrypto,TextEncoder,
    setTimeout:timeout,clearTimeout:clear,URL
  });
  state.pump=()=>{
    const next=state.timers.find(x=>x.live);
    if(!next)throw Error("NO_PENDING_SCAN");
    next.live=false;
    next.fn();
  };
  state.scan=()=>{for(const l of state.listeners)l({type:"BCT_BRIDGE_SCAN_NOW"});state.pump()};
  return state;
}
async function settle(predicate) {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    if (predicate()) { await new Promise(resolve => setTimeout(resolve, 10)); return; }
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw Error("ASYNC_SCAN_DID_NOT_SETTLE");
}
test("activation baselines old marker and dispatches only a newer assistant message",async()=>{
  const h=harness();h.pump();
  await settle(()=>h.statusCalls>=1);
  assert.equal(h.readCalls.length,0,"old assistant marker may not dispatch");
  h.scan();
  await settle(()=>h.statusCalls>=2);
  assert.equal(h.readCalls.length,0);
  h.nodes.push({innerText:marker});
  h.scan();
  await settle(()=>h.readCalls.length===1);
  assert.equal(h.readCalls[0].grantId,grantA);
  h.grant=null;
  h.resolveRead({ok:true,result:{text:"fixture"}});
  await settle(()=>h.store.has("bct-chat-delivery-uncertain:6ad733b6-95d4-83ee-b4ba-49a671229d77:101"));
  assert.equal(h.clicks,0);
});
test("revocation while read is in flight prevents automatic result submit",async()=>{
  const h=harness();h.pump();
  await settle(()=>h.statusCalls>=1);
  h.nodes.push({innerText:marker});h.scan();
  await settle(()=>h.readCalls.length===1);
  h.grant=null;
  h.resolveRead({ok:true,result:{text:"fixture"}});
  const key="bct-chat-delivery-uncertain:6ad733b6-95d4-83ee-b4ba-49a671229d77:101";
  await settle(()=>h.store.has(key));
  assert.equal(h.store.get(key).outcome,"CHAT_GRANT_REVOKED_NO_SEND");
  assert.equal(h.clicks,0);
  assert.equal(h.editor.innerText,"");
  assert.equal(h.readCalls.length,1);
});
test("re-enable with new grant cannot publish old in-flight result",async()=>{
  const h=harness();h.pump();
  await settle(()=>h.statusCalls>=1);
  h.nodes.push({innerText:marker});h.scan();
  await settle(()=>h.readCalls.length===1);
  h.grant=grantB;
  h.resolveRead({ok:true,result:{text:"fixture"}});
  const key="bct-chat-delivery-uncertain:6ad733b6-95d4-83ee-b4ba-49a671229d77:101";
  await settle(()=>h.store.has(key));
  assert.equal(h.clicks,0);
  assert.equal(h.store.get(key).outcome,"CHAT_GRANT_REVOKED_NO_SEND");
  h.scan();
  await settle(()=>h.statusCalls>=5);
  assert.equal(h.readCalls.length,1,"old marker may not resend on re-enable");
});
