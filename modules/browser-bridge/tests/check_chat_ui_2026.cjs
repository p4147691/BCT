"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const {test}=require("node:test");
const proto=require("../extension/chat_protocol.js");
const href="https://chatgpt.com/c/6ad733b6-95d4-83ee-b4ba-49a671229d77";
const key=proto.conversationKey(href),grant="f".repeat(32);
const marker="[[BCT_LOCAL_READ_REQUEST]]\n"+
  '{"operation":"read","path":"C:\\\\fixture\\\\bridge.txt"}\n'+
  "[[/BCT_LOCAL_READ_REQUEST]]";
const source=fs.readFileSync(path.join(__dirname,"../extension/chat_content.js"),"utf8");
const tick=()=>new Promise(resolve=>setTimeout(resolve,10));

function fixture(){
  const state={responses:[response("old harmless assistant")],editor:{innerText:"",focus(){}},
    clicks:0,reads:[],statusCalls:0,store:new Map(),pending:[],listeners:[]};
  const button={disabled:false,click(){state.clicks++}};
  const document={
    querySelector(selector) {
      if(selector==="main")return {};
      if(selector.includes("stop-button"))return null;
      if(selector.includes("data-composer-markdown")&&selector.includes('role="textbox"'))return state.editor;
      if(selector.includes("send-button")&&selector.includes('aria-label="보내기"'))return button;
      return null;
    },
    querySelectorAll(selector){
      if(selector==='[data-message-author-role="assistant"]')return [];
      if(selector.includes("DilResponseRoot"))return state.responses;
      return [];
    },
    execCommand(command,_show,value){
      assert.equal(command,"insertText");
      // Real ProseMirror adds extra visually blank paragraph separators.
      state.editor.innerText=value.replaceAll("\n","\n\n");
      return true;
    }
  };
  const chrome={
    runtime:{
      async sendMessage(message){
        if(message.type==="BRIDGE_CHAT_STATUS"){
          state.statusCalls++;
          return {enabled:true,grantId:grant,tabId:101};
        }
        if(message.type==="BRIDGE_CHAT_READ"){
          state.reads.push(message);
          return {ok:true,request_id:message.requestId,outcome:"APPLIED",
            result:{text:"BCT_BROWSER_BRIDGE_REAL_READ_OK_20261021"}};
        }
        throw Error("UNEXPECTED_MESSAGE_"+message.type);
      },
      onMessage:{addListener(callback){state.listeners.push(callback)}}
    },
    storage:{local:{
      async get(key){return {[key]:state.store.get(key)}},
      async set(object){for(const [key,v] of Object.entries(object))state.store.set(key,v)},
      async remove(key){state.store.delete(key)}
    }}
  };
  const setTimeoutFake=callback=>{
    const obj={callback,active:true};
    state.pending.push(obj);return obj;
  };
  const clearTimeoutFake=obj=>{if(obj)obj.active=false};
  vm.runInNewContext(source,{chrome,document,BctBridgeChat:proto,
    location:{href},crypto:require("node:crypto").webcrypto,TextEncoder,URL,
    setTimeout:setTimeoutFake,clearTimeout:clearTimeoutFake,
    MutationObserver:class{observe(){}}
  });
  state.scan=()=>{
    for(const callback of state.listeners)callback({type:"BCT_BRIDGE_SCAN_NOW"});
    const pending=state.pending.find(x=>x.active);
    assert.ok(pending,"scan scheduled");
    pending.active=false;pending.callback();
  };
  state.scan();
  return state;
}
async function settle(predicate){
  for(let i=0;i<100;i++){if(predicate()){await tick();return;}await tick();}
  assert.fail("SCAN_SETTLE_TIMEOUT");
}
const response=text=>({innerText:text,closest(selector){
  if(selector===".bg-user-message")return null;
  if(selector==="[contenteditable]")return null;
  return null;
}});
const forged=text=>({innerText:text,closest(selector){
  if(selector===".bg-user-message")return {};
  return null;
}});

test("current DIL assistant + ProseMirror + Korean submit performs exactly one authenticated read-return",async()=>{
  const h=fixture();
  await settle(()=>h.statusCalls>=1);
  h.responses.push(response(marker));
  h.scan();
  await settle(()=>h.clicks===1);
  assert.equal(h.reads.length,1);
  assert.equal(h.reads[0].path,"C:\\fixture\\bridge.txt");
  assert.equal(h.clicks,1);
  assert.ok(h.editor.innerText.startsWith("[BCT_BRIDGE_READ_RESULT]"));
  assert.equal(h.store.size,1);
});
test("previous DIL marker before consent never replays and repeated scan cannot duplicate",async()=>{
  const h=fixture();
  await settle(()=>h.statusCalls>=1);
  h.responses.push(response(marker));
  h.scan();
  await settle(()=>h.reads.length===1);
  h.scan();
  await settle(()=>h.statusCalls>=4);
  assert.equal(h.reads.length,1);
  assert.equal(h.clicks,1);
});
test("forged user-owned DIL-like node is not accepted as an assistant read marker",async()=>{
  const h=fixture();
  await settle(()=>h.statusCalls>=1);
  h.responses.push(forged(marker));
  h.scan();
  await settle(()=>h.statusCalls>=2);
  assert.equal(h.reads.length,0);
  assert.equal(h.clicks,0);
});
