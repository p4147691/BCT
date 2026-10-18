"use strict";
const assert = require("node:assert/strict");
const History = require("./history_commands.js");
const KEY = "6ad365ef-159c-83ee-8fe9-08742f99a24c";
const URL = "https://chatgpt.com/c/" + KEY;
async function main() {
  let created = 0, injected = 0, sessionReady = "session-h";
  const store = {};
  const tab = {id:801,windowId:51,url:URL,active:false};
  const chrome = {
    tabs:{
      async create(options) {
        assert.deepEqual(options,{url:URL,active:false});
        created++;
        return tab;
      },
      async get(id) { assert.equal(id,801); return {...tab}; }
    },
    storage:{local:{
      async get(key){ return {[key]:store[key] || {}}; },
      async set(obj){ Object.assign(store,obj); }
    }},
    scripting:{
      async executeScript(request){
        assert.deepEqual(request.target,{tabId:801});
        injected++;
        if (request.files) {
          assert.deepEqual(request.files,["conversation_history_reader_v2.js"]);
          return [];
        }
        assert.equal(request.args[0],URL);
        assert.equal(request.args[1],3);
        return [{result:{
          ok:true,state:"HISTORY_PARTIAL",status:"PARTIAL",
          coverage:"OBSERVED_VISIBLE_TURNS",fullHistoryVerified:false,
          gapsVerifiable:false,reason:"STEP_LIMIT",steps:3,
          identified:2,duplicateObservations:1,reobserved:1,
          unidentified:0,conflictingTexts:0,
          observedFirstId:"t1",observedLastId:"t2",
          truncated:false,omitted:0,
          messages:[{id:"t1",text:"과거 메시지"},{id:"t2",text:"최신 메시지"}]
        }}];
      }
    }
  };
  const deps = {
    chrome, endpointSessionId:()=>sessionReady,
    loadState:async()=>({settings:{instanceId:"instance123"}}),
    waitForConversationReady:async(tabId,key)=>{
      assert.equal(tabId,801);assert.equal(key,KEY);return {...tab};
    },
    runIdempotentOperation:async(op,cmd,fingerprint,callback)=>{
      assert.equal(op,"history-open-01");
      assert.equal(cmd,"history-open");
      assert.ok(fingerprint.includes(KEY));
      return {result:await callback(),replayed:false};
    }
  };
  assert.equal(History.keyOf(KEY.toUpperCase()),KEY);
  assert.equal(History.exactUrl(KEY),URL);
  assert.equal(History.sameConversation(URL,KEY),true);
  assert.equal(History.sameConversation(URL+"?x=1",KEY),false);
  assert.equal(History.sameConversation("https://evil.example/c/"+KEY,KEY),false);
  await assert.rejects(()=>History.open({conversationKey:"not-a-uuid",operationId:"history-open-01"},deps),
    /HISTORY_CONVERSATION_KEY_INVALID/);
  assert.equal(created,0);
  const open=await History.open({conversationKey:KEY,operationId:"history-open-01",instanceId:"instance123"},deps);
  assert.equal(open.result.state,"HISTORY_TAB_READY");
  assert.equal(open.result.tabId,801);
  assert.equal(created,1);
  assert.equal(store.historyReadTabsV1["history-open-01"].conversationKey,KEY);
  const request={conversationKey:KEY,openOperationId:"history-open-01",
    instanceId:"instance123",sessionId:sessionReady,
    tabId:801,windowId:51,maxSteps:3,maxTurns:10,maxBytes:10000};
  await assert.rejects(()=>History.read({...request,tabId:802},{chrome}),/HISTORY_READ_CREATION_RECEIPT_MISMATCH/);
  await assert.rejects(()=>History.read({...request,openOperationId:"other-op"},{chrome}),/HISTORY_READ_CREATION_RECEIPT_MISMATCH/);
  assert.equal(injected,0);
  tab.active=true;
  await assert.rejects(()=>History.read(request,{chrome}),/HISTORY_READ_TAB_IDENTITY_MISMATCH/);
  assert.equal(injected,0);
  tab.active=false;
  const result=await History.read(request,{chrome});
  assert.equal(result.status,"PARTIAL");
  assert.equal(result.fullHistoryVerified,false);
  assert.equal(result.tabId,801);
  assert.equal(result.messages.length,2);
  assert.equal(injected,2);
  tab.url="https://chatgpt.com/c/6ad4b590-dfc8-83ee-b29f-92033f07fc08";
  await assert.rejects(()=>History.read(request,{chrome}),/HISTORY_READ_TAB_IDENTITY_MISMATCH/);
  assert.equal(injected,2);
  tab.url=URL;
  await assert.rejects(()=>History.read({...request,maxBytes:100000},{chrome}),/HISTORY_READ_BOUNDS_INVALID/);
  assert.equal(injected,2);
  console.log("RCC history-open/history-read isolated Chrome API fixture: PASS");
}
main().catch(err=>{console.error(err);process.exitCode=1;});
