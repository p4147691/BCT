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
const marker = (value) => "[[BCT_LOCAL_READ_REQUEST]]\n" + value + "\n[[/BCT_LOCAL_READ_REQUEST]]";

test("canonical one-operation read marker only", () => {
  assert.deepEqual(api.parseReadMarker(marker('{"operation":"read","path":"D:\\\\BCT\\\\source\\\\README.md"}')),
    {operation: "read", path: "D:\\BCT\\source\\README.md"});
  assert.equal(api.parseReadMarker(marker('{"path":"D:\\\\BCT","operation":"read"}')), null);
  assert.equal(api.parseReadMarker(marker('{"operation":"read","path":"x","operation":"read"}')), null);
  assert.equal(api.parseReadMarker(marker('{"operation":"write","path":"x"}')), null);
  assert.equal(api.parseReadMarker(marker('{"operation":"read","path":"x","shell":"whoami"}')), null);
  assert.equal(api.parseReadMarker(marker('{"operation":"read","path":"x"}') + "\nadditional"), null);
  assert.equal(api.parseReadMarker("hello " + marker('{"operation":"read","path":"x"}')), null);
  assert.equal(api.parseReadMarker(marker('{"operation":"read","path":""}')), null);
});
test("exact chat URL and sender identity", () => {
  assert.equal(api.conversationKey(chatUrl), conversation);
  assert.equal(api.conversationKey("https://evil.example/c/" + conversation), null);
  assert.equal(api.conversationKey("https://chatgpt.com/"), null);
  assert.equal(api.conversationKey(chatUrl + "/misc"), null);
  const sender = {id: extensionId, frameId: 0, url: chatUrl, tab: {id: 101, url: chatUrl}};
  assert.equal(api.validChatSender(sender, extensionId, conversation), true);
  assert.equal(api.validChatSender({...sender, id: "other"}, extensionId, conversation), false);
  assert.equal(api.validChatSender({...sender, frameId: 1}, extensionId, conversation), false);
  assert.equal(api.validChatSender({...sender, tab: {id: 101, url: "https://chatgpt.com/"}}, extensionId, conversation), false);
  assert.equal(api.validChatSender(sender, extensionId, "other"), false);
});
function createBackground(consents={}) {
  const callbacks={}; const posted=[]; const consent={...consents};
  const port={onMessage:{addListener(fn){callbacks.reply=fn}},
    onDisconnect:{addListener(fn){callbacks.disconnect=fn}},
    postMessage(value){posted.push(value)}};
  const chrome={
    runtime:{id:extensionId, connectNative(name){assert.equal(name,"com.bct.browser_bridge.prototype");return port},
      onMessage:{addListener(fn){callbacks.message=fn}}},
    storage:{session:{async get(key){return {[key]:consent[key]}}}}
  };
  const sandbox={chrome, BctBridgeChat:api, crypto:require("node:crypto").webcrypto,
    importScripts(name){assert.equal(name,"chat_protocol.js")},URL};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../extension/background.js"),"utf8"),sandbox);
  return {callbacks,posted,consent};
}
test("unapproved, wrong tab and forged sender never reach native host", async () => {
  const b=createBackground();
  const requestId="a".repeat(32);
  const sender={id:extensionId,frameId:0,url:chatUrl,tab:{id:101,url:chatUrl}};
  const request={type:"BRIDGE_CHAT_READ",conversationKey:conversation,requestId,path:"D:\\BCT\\source\\README.md"};
  const replies=[];
  assert.equal(b.callbacks.message(request,sender,v=>replies.push(v)),true);
  await new Promise(setImmediate);
  assert.equal(b.posted.length,0);
  assert.equal(replies[0]?.error,"CHAT_NOT_ENABLED");

  assert.equal(b.callbacks.message(request,{...sender,tab:{id:102,url:chatUrl}},v=>replies.push(v)),true);
  await new Promise(setImmediate);
  assert.equal(b.posted.length,0);

  assert.equal(b.callbacks.message(request,{...sender,frameId:1},v=>replies.push(v)),false);
  assert.equal(b.posted.length,0);
});
test("authorized read has one exact operation; no retry after native disconnect", async () => {
  const b=createBackground({["bct-chat-consent:"+conversation+":101"]:true});
  const requestId="b".repeat(32);
  const sender={id:extensionId,frameId:0,url:chatUrl,tab:{id:101,url:chatUrl}};
  const request={type:"BRIDGE_CHAT_READ",conversationKey:conversation,requestId,path:"D:\\BCT\\source\\README.md"};
  let reply;
  assert.equal(b.callbacks.message(request,sender,v=>{reply=v}),true);
  await new Promise(setImmediate);
  assert.equal(b.posted.length,1);
  assert.equal(b.posted[0].operation_id,requestId);
  assert.equal(b.posted[0].type,"bridge_read");
  b.callbacks.disconnect();
  assert.equal(reply.error,"NATIVE_DISCONNECTED_NO_RETRY");
  assert.equal(b.posted.length,1);
});
test("sender cannot override capability or introduce extra arguments", () => {
  const b=createBackground();
  const sender={id:extensionId,frameId:0,url:chatUrl,tab:{id:101,url:chatUrl}};
  let reply;
  const value={type:"BRIDGE_CHAT_READ",conversationKey:conversation,requestId:"c".repeat(32),
    path:"C:\\ok",capability:"execute"};
  assert.equal(b.callbacks.message(value,sender,v=>{reply=v}),false);
  assert.equal(reply.error,"CHAT_REQUEST_DENIED");
  assert.equal(b.posted.length,0);
});
