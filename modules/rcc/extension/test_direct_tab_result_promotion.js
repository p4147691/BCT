'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { randomUUID, webcrypto } = require('node:crypto');

const source = fs.readFileSync('modules/rcc/extension/background.js', 'utf8');
const iid = '6174664e1c1b4e6db1d4729c841db3c9';
const sid = 'd59b87382f3a4236bb5c00dff143c344';
const work = 'BCT-RCC-DIRECT-FOLLOWUP-FIX-ISOLATED-20261019-01';
const firstKey = '6ad5b191-947c-83ee-8dae-b9c867af9026';
const secondKey = '6ad5877a-f014-83ec-a97a-b38c838a429c';
const snapshot = value => JSON.parse(JSON.stringify(value));

function makeHarness(tabIds = [7219]) {
  const tabs = new Map(tabIds.map(id => [id, {
    id, windowId: 7281, url: 'https://chatgpt.com/', title: 'ChatGPT'
  }]));
  const store = {
    registrations: {}, settings: {instanceId: iid, token: 'fixture', armed: false, budget: 0},
    pending: {}, operations: {}, results: [], processed: []
  };
  const unexpected = [];
  const chrome = {
    storage: {local: {
      get: async keys => {
        const result = {};
        for (const key of (Array.isArray(keys) ? keys : Object.keys(store))) {
          if (Object.prototype.hasOwnProperty.call(store,key)) result[key] = snapshot(store[key]);
        }
        return result;
      },
      set: async changes => {
        for (const [k,v] of Object.entries(changes)) store[k] = snapshot(v);
      }
    }},
    tabs: {
      get: async id => {
        const tab = tabs.get(Number(id)); if (!tab) throw Error('MOCK_TAB_NOT_FOUND');
        return {...tab};
      },
      query: async () => [...tabs.values()].map(t => ({...t})),
      sendMessage: async (_id,payload) => { if (payload?.type === 'relay:execute') {unexpected.push('REAL_SEND'); throw Error('UNEXPECTED_CHROME_SEND');} return {ok:true}; },
      create: async () => { unexpected.push('CREATE'); throw Error('UNEXPECTED_CHROME_CREATE'); },
      onCreated: {addListener(){}}, onUpdated: {addListener(){}}, onRemoved: {addListener(){}}
    },
    scripting: {executeScript: async () => { throw Error('UNEXPECTED_SCRIPT_INJECTION'); }},
    runtime: {
      id: 'mock', connectNative: () => ({
        onMessage: {addListener(){}}, onDisconnect: {addListener(){}}, postMessage(){}
      }),
      onMessage: {addListener(){}}, onStartup: {addListener(){}}, onInstalled: {addListener(){}}
    }
  };
  const ctx = {
    URL, console, TextEncoder, Uint8Array,
    crypto: {randomUUID, subtle:webcrypto.subtle},
    setTimeout: () => 0, clearTimeout: () => {},
    setInterval: () => 0, clearInterval: () => {}, chrome,
    RelayCore: {
      normalizeRole: x => String(x).trim().toUpperCase(),
      conversationKey: url => (String(url).match(/\/c\/([a-f0-9-]{36})/) || [])[1] || '',
      makeResultEnvelope: () => ''
    }
  };
  vm.createContext(ctx);
  vm.runInContext(source,ctx);
  vm.runInContext("endpointSessionId='"+sid+"';",ctx);
  const submits = [];
  ctx.sendToChatTab = async (id,payload) => {
    assert.ok(tabs.has(id));
    assert.equal(payload.type,'relay:execute');
    submits.push({tabId:id,bootstrap:payload.bootstrapCreatedTab===true});
    return {ok:true,submitted:true,deliveryConfirmed:true,stageTiming:{sendButtonReadyAt:1,sendButtonClickedAt:2}};
  };
  const request = (id,operationId,conversationKey='') => ({
    operationId,instanceId:iid,sessionId:sid,workId:work,
    tabId:id,windowId:7281,conversationKey,text:'bounded isolated synthetic text'
  });
  function receipt(op) {
    return Object.values(store).flatMap(v => v && typeof v==='object' ? [v[op]] : [])
      .find(v => v && typeof v==='object' && v.routeId===op && v.resultHash);
  }
  return {ctx,tabs,store,submits,request,receipt,unexpected};
}

async function firstSubmission(h,id=7219,op='first') {
  const r=await h.ctx.sendToExistingTab(h.request(id,op));
  assert.equal(r.result.state,'SUBMITTED');
  assert.equal(h.store.registrations['BCT_TAB_'+id].authorization,'ACT_CONVERSATION_BOOTSTRAP');
  return r;
}

async function testPromotionAndHash() {
  const h=makeHarness();
  await firstSubmission(h);
  assert.equal(h.store.registrations['BCT_TAB_7219'].conversationKey,'');
  h.tabs.get(7219).url='https://chatgpt.com/c/'+firstKey;
  const result={ok:true,reply:'isolated response payload'};
  const done=await h.ctx.deliverResult('first',result,7219);
  assert.equal(done.returnState,'NOT_REQUESTED');
  const reg=h.store.registrations['BCT_TAB_7219'];
  assert.equal(reg.conversationKey,firstKey);
  assert.equal(reg.authorization,'ACT_CONVERSATION_BIND');
  assert.ok(reg.bootstrapConsumedAt);
  const receipt=h.receipt('first');
  assert.ok(receipt,'durable first result required');
  assert.match(receipt.resultHash,/^[a-f0-9]{64}$/);
  assert.equal(receipt.ackState,'UNACKED');
  assert.equal(receipt.returnState,'NOT_REQUESTED');
  assert.equal(receipt.resultState,'RESULT_PERSISTED');
  assert.equal(receipt.conversationKey,firstKey);
  assert.equal(receipt.resultPayload.reply,result.reply);
  assert.equal(Object.keys(h.store.pending).length,0);
  const duplicate=await h.ctx.deliverResult('first',result,7219);
  assert.equal(duplicate.duplicate,true,'no repeated effects for same RESULT');
  assert.equal(h.receipt('first').resultHash,receipt.resultHash);
  await assert.rejects(
    h.ctx.deliverResult('first',{ok:true,reply:'forged duplicate'},7219),
    /RELAY_RESULT_CONFLICT/,
    'different reply must never replace the durable hash'
  );
  assert.equal(h.receipt('first').resultHash,receipt.resultHash);
  const sameOperation=await h.ctx.sendToExistingTab(h.request(7219,'first',''));
  assert.equal(sameOperation.replayed,true,'duplicate operation must not dispatch');
  assert.equal(h.submits.length,1);
  await assert.rejects(
    h.ctx.sendToExistingTab(h.request(7219,'wrong-blank-key','')),
    /DIRECT_TAB_CONVERSATION_MISMATCH/
  );
  assert.equal(h.submits.length,1);
  const second=await h.ctx.sendToExistingTab(h.request(7219,'second',firstKey));
  assert.equal(second.result.state,'SUBMITTED');
  assert.equal(h.submits.length,2);
  assert.equal(h.submits[0].bootstrap,true);
  assert.equal(h.submits[1].bootstrap,false);
  await h.ctx.deliverResult('second',{ok:true,reply:'second response'},7219);
  assert.equal(h.receipt('second').resultState,'RESULT_PERSISTED');
  assert.equal(h.store.registrations['BCT_TAB_7219'].conversationKey,firstKey);
  assert.equal(h.unexpected.length,0);
  return {firstResultHash:receipt.resultHash,secondResultHash:h.receipt('second').resultHash};
}

async function testTwoConcurrentPromotions() {
  const h=makeHarness([7219,7220]);
  await firstSubmission(h,7219,'first-a');
  await firstSubmission(h,7220,'first-b');
  h.tabs.get(7219).url='https://chatgpt.com/c/'+firstKey;
  h.tabs.get(7220).url='https://chatgpt.com/c/'+secondKey;
  const out=await Promise.all([
    h.ctx.deliverResult('first-a',{ok:true,reply:'a'},7219),
    h.ctx.deliverResult('first-b',{ok:true,reply:'b'},7220)
  ]);
  assert.equal(out.length,2);
  assert.equal(h.store.registrations['BCT_TAB_7219'].conversationKey,firstKey);
  assert.equal(h.store.registrations['BCT_TAB_7220'].conversationKey,secondKey);
  assert.equal(h.store.registrations['BCT_TAB_7219'].authorization,'ACT_CONVERSATION_BIND');
  assert.equal(h.store.registrations['BCT_TAB_7220'].authorization,'ACT_CONVERSATION_BIND');
  assert.ok(h.receipt('first-a')?.resultHash);
  assert.ok(h.receipt('first-b')?.resultHash);
  assert.equal(h.unexpected.length,0);
}

async function testMutatedRoleRejectedWithoutOverwrite() {
  const h=makeHarness();
  await firstSubmission(h);
  h.tabs.get(7219).url='https://chatgpt.com/c/'+firstKey;
  const r=h.store.registrations['BCT_TAB_7219'];
  r.directTabOperationId='stolen-other-operation';
  await assert.rejects(
    h.ctx.deliverResult('first',{ok:true,reply:'a'},7219),
    /DIRECT_TAB_RESULT_BINDING_CHANGED/
  );
  assert.equal(h.store.registrations['BCT_TAB_7219'].directTabOperationId,'stolen-other-operation');
  assert.equal(h.store.registrations['BCT_TAB_7219'].conversationKey,'');
  assert.ok(h.receipt('first')?.resultHash,'durable RESULT must be preserved');
  assert.equal(Object.keys(h.store.pending).length,1,'pending must not be cleared on unsafe mutation');
  assert.equal(h.unexpected.length,0);
}

async function testActiveLeaseNotBypassed() {
  const h=makeHarness();
  await firstSubmission(h);
  h.tabs.get(7219).url='https://chatgpt.com/c/'+firstKey;
  const leaseId='other-pending-lease';
  const leaseKey=Object.keys(h.store).find(x => /bindingSubmitLeases/i.test(x));
  h.store[leaseKey || 'bindingSubmitLeases']={
    [leaseId]:{role:'BCT_TAB_7219',tabId:7219,conversationKey:'',expiresAt:Date.now()+120000}
  };
  await assert.rejects(
    h.ctx.deliverResult('first',{ok:true,reply:'a'},7219),
    /PRE_SUBMIT_BINDING_LEASE_ACTIVE/
  );
  assert.equal(h.store.registrations['BCT_TAB_7219'].conversationKey,'');
  const stored=h.receipt('first');
  assert.ok(stored?.resultHash);
  assert.equal(Object.keys(h.store.pending).length,1);
  h.store[leaseKey || 'bindingSubmitLeases']={};
  const recovered=await h.ctx.deliverResult('first',{ok:true,reply:'a'},7219);
  assert.equal(recovered.returnState,'NOT_REQUESTED');
  assert.equal(h.store.registrations['BCT_TAB_7219'].conversationKey,firstKey);
  assert.equal(h.receipt('first').resultHash,stored.resultHash);
  assert.equal(h.submits.length,1,'lease recovery must never resend');
}

(async()=>{
  const output=await testPromotionAndHash();
  await testTwoConcurrentPromotions();
  await testMutatedRoleRejectedWithoutOverwrite();
  await testActiveLeaseNotBypassed();
  console.log('RCC_DIRECT_TAB_RESULT_PROMOTION_PASS cases=4 hash='+output.firstResultHash.slice(0,12));
})().catch(e=>{console.error(e);process.exitCode=1;});
