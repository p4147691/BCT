"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const api = require("../extension/chat_protocol.js");
const extensionId = "acdgnmbgpkfjkckccbhmccojgigbfcge";
const conversation = "6ad733b6-95d4-83ee-b4ba-49a671229d77";
const chatUrl = "https://chatgpt.com/c/" + conversation;
const grant = "f".repeat(32);
const marker = v => "[[BCT_LOCAL_READ_REQUEST]]\n" + v + "\n[[/BCT_LOCAL_READ_REQUEST]]";
const consentKey = "bct-chat-consent:" + conversation + ":101";
const sender = {id:extensionId,frameId:0,url:chatUrl,tab:{id:101,url:chatUrl}};
const read = () => ({type:"BRIDGE_CHAT_READ",conversationKey:conversation,grantId:grant,
  requestId:"a".repeat(32),path:"D:\\BCT\\source\\README.md"});

test("canonical one-operation read marker only", () => {
  assert.deepEqual(api.parseReadMarker(marker('{"operation":"read","path":"D:\\\\BCT\\\\source\\\\README.md"}')),
    {operation:"read",path:"D:\\BCT\\source\\README.md"});
  for (const text of [
    marker('{"path":"x","operation":"read"}'), marker('{"operation":"read","path":"x","operation":"read"}'),
    marker('{"operation":"write","path":"x"}'), marker('{"operation":"read","path":"x","shell":"whoami"}'),
    marker('{"operation":"read","path":""}'),"hello "+marker('{"operation":"read","path":"x"}')
  ]) assert.equal(api.parseReadMarker(text),null);
});
test("exact chat URL and sender identity", () => {
  assert.equal(api.conversationKey(chatUrl),conversation);
  assert.equal(api.conversationKey("https://evil.example/c/"+conversation),null);
  assert.equal(api.conversationKey("https://chatgpt.com/"),null);
  assert.equal(api.conversationKey(chatUrl+"/misc"),null);
  assert.equal(api.validChatSender(sender,extensionId,conversation),true);
  assert.equal(api.validChatSender({...sender,id:"wrong"},extensionId,conversation),false);
  assert.equal(api.validChatSender({...sender,frameId:1},extensionId,conversation),false);
  assert.equal(api.validChatSender({...sender,tab:{id:101,url:"https://chatgpt.com/"}},extensionId,conversation),false);
});
function createBackground(initial={}) {
  const callbacks={},posted=[],consent={...initial};
  const port={onMessage:{addListener(fn){callbacks.reply=fn}},
    onDisconnect:{addListener(fn){callbacks.disconnect=fn}},
    postMessage(body){posted.push(body)}};
  const chrome={
    runtime:{id:extensionId,connectNative(name){assert.equal(name,"com.bct.browser_bridge.prototype");return port},
      onMessage:{addListener(fn){callbacks.message=fn}}},
    storage:{session:{async get(key){return {[key]:consent[key]}}}}
  };
  const ctx={chrome,BctBridgeChat:api,crypto:require("node:crypto").webcrypto,
    importScripts(name){assert.equal(name,"chat_protocol.js")},URL};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../extension/background.js"),"utf8"),ctx);
  return {callbacks,posted,consent};
}
const tick = () => new Promise(resolve=>setImmediate(resolve));
test("no consent, foreign tab or forged sender reaches host", async () => {
  const b=createBackground(),replies=[];
  assert.equal(b.callbacks.message(read(),sender,x=>replies.push(x)),true);
  await tick();
  assert.equal(b.posted.length,0);
  assert.equal(replies[0]?.error,"CHAT_GRANT_REVOKED");
  assert.equal(b.callbacks.message(read(),{...sender,frameId:1},x=>replies.push(x)),false);
  assert.equal(b.posted.length,0);
});
test("authorized exact grant yields one read, disconnect causes no resend",async()=>{
  const b=createBackground({[consentKey]:grant});let reply;
  assert.equal(b.callbacks.message(read(),sender,x=>reply=x),true);
  await tick();
  assert.equal(b.posted.length,1);
  assert.equal(b.posted[0].operation_id,read().requestId);
  assert.equal(b.posted[0].type,"bridge_read");
  b.callbacks.disconnect();
  assert.equal(reply.error,"NATIVE_DISCONNECTED_NO_RETRY");
  assert.equal(b.posted.length,1);
});
test("sender cannot override capability or add fields",()=>{
  const b=createBackground({[consentKey]:grant});let reply;
  assert.equal(b.callbacks.message({...read(),capability:"execute"},sender,x=>reply=x),false);
  assert.equal(reply.error,"CHAT_REQUEST_DENIED");
  assert.equal(b.posted.length,0);
});
test("consent rotation rejects stale in-flight grant before native dispatch",async()=>{
  const b=createBackground({[consentKey]:"b".repeat(32)});let reply;
  assert.equal(b.callbacks.message(read(),sender,x=>reply=x),true);
  await tick();
  assert.equal(reply?.error,"CHAT_GRANT_REVOKED");
  assert.equal(b.posted.length,0);
});
test("status exposes only an exact 32-hex grant for that tab",async()=>{
  const b=createBackground({[consentKey]:grant});let response;
  b.callbacks.message({type:"BRIDGE_CHAT_STATUS",conversationKey:conversation},sender,x=>response=x);
  await tick();
  assert.equal(response.enabled,true);
  assert.equal(response.grantId,grant);
  assert.equal(response.tabId,101);
  b.consent[consentKey]=true;
  b.callbacks.message({type:"BRIDGE_CHAT_STATUS",conversationKey:conversation},sender,x=>response=x);
  await tick();
  assert.equal(response.enabled,false);
});
