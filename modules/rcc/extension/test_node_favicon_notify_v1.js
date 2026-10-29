'use strict';
// Isolated actual RCC JS modules, no operating Chrome or native host.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { randomUUID } = require('node:crypto');

const SRC = (x) => fs.readFileSync(__dirname + '/' + x, 'utf8');
const UUID = '6ae269f6-130c-83ee-9384-dffa2d2a946d';
const OTHER = '6ae295f6-8090-83e8-b444-02d46f637c20';
const INSTANCE = 'a'.repeat(32), SESSION = 'b'.repeat(32);
const tab = (uuid=UUID, id=71, win=22) => ({
  id,windowId:win,url:'https://chatgpt.com/c/'+uuid
});
const command = (changes={}) => ({
  eventId:12, conversationKey:UUID, tabId:71, windowId:22,
  sessionId:SESSION, instanceId:INSTANCE, ...changes,
});
function setup(changes={}) {
  const calls=[];let active=tab();
  let peers=[active];
  const api={
    getExactTab:async()=>active,
    sendWithReceiver:async(id,msg)=>{
      calls.push({id,msg});
      if (changes.throwSend) throw Error('simulated lost ACK');
      return changes.ack || {ok:true,eventId:msg.eventId,conversationKey:msg.conversationKey};
    }
  };
  const ctx=vm.createContext({
    browserGateway:api, endpointSessionId:SESSION,
    isChatTab:x=>!!x&&x.url.startsWith('https://chatgpt.com/'),
    RelayCore:{conversationKey:url=>/\/c\/([0-9a-f-]{36})/.exec(url)?.[1]||''},
    loadState:async()=>({settings:{instanceId:INSTANCE}}),
    getChatTabs:async()=>peers,
  });
  vm.runInContext(SRC('domain/node_favicon_notify_service.js'),ctx);
  return {run:msg=>vm.runInContext('notifyNodeFaviconChanged',ctx)(msg,'node-label.12.71'),
    calls, setTab:x=>{active=x}, setPeers:x=>{peers=x}};
}

async function check(name,fn) {await fn();console.log('PASS '+name);}
(async()=>{
  await check('exact UUID/tab/window/session acknowledgement only',async()=>{
    const f=setup();const reply=await f.run(command());
    assert.equal(reply.ok,true);assert.equal(reply.state,'DELIVERED');
    assert.equal(f.calls.length,1);
    assert.equal(JSON.stringify(f.calls[0]),JSON.stringify({id:71,msg:{type:'relay:nodeLabelNotify',eventId:12,conversationKey:UUID}}));
    assert.ok(!('nodeLabel' in f.calls[0].msg));
  });
  await check('duplicate event is idempotent without sending twice',async()=>{
    const f=setup();await f.run(command());
    const duplicate=await f.run(command());
    assert.equal(duplicate.duplicate,true);assert.equal(f.calls.length,1);
  });
  await check('session and instance mismatch fail closed',async()=>{
    const f=setup();assert.equal((await f.run(command({sessionId:'f'.repeat(32)}))).ok,false);
    assert.equal((await f.run(command({instanceId:'c'.repeat(32)}))).ok,false);
    assert.equal(f.calls.length,0);
  });
  await check('wrong UUID and window reject delivery',async()=>{
    const f=setup();assert.equal((await f.run(command({conversationKey:OTHER}))).ok,false);
    assert.equal((await f.run(command({windowId:99}))).ok,false);
    assert.equal(f.calls.length,0);
  });
  await check('same UUID in two tabs rejects ambiguous target',async()=>{
    const f=setup();f.setPeers([tab(),tab(UUID,72)]);
    const reply=await f.run(command());
    assert.equal(reply.error,'NODE_FAVICON_AMBIGUOUS_UUID');
    assert.equal(f.calls.length,0);
  });
  await check('network/receiver failure is UNKNOWN, not success',async()=>{
    const f=setup({throwSend:true});const reply=await f.run(command());
    assert.equal(reply.effectState,'UNKNOWN');
    assert.equal(reply.ok,false);
  });
  await check('navigation after dispatch rejects unverified completion',async()=>{
    const f=setup();
    f.setTab(tab(OTHER));
    const reply=await f.run(command());
    assert.equal(reply.effectState,'NOT_APPLIED');assert.equal(f.calls.length,0);
  });
  await check('content receiver dispatches DOM notification once for exact conversation',async()=>{
    const replies=[],events=[];let handler;
    const ctx=vm.createContext({
      chrome:{runtime:{id:'trusted-rcc',onMessage:{addListener:fn=>handler=fn}}},
      currentConversationKey:()=>UUID,
      window:{dispatchEvent:e=>events.push(e.type)},
      Event:class{constructor(type){this.type=type}},
    });
    vm.runInContext(SRC('content/content_router.js'),ctx);
    const sendResponse = x=>replies.push(x);
    handler({type:'relay:nodeLabelNotify',eventId:12,conversationKey:UUID},
      {id:'trusted-rcc'},sendResponse);
    handler({type:'relay:nodeLabelNotify',eventId:12,conversationKey:UUID},
      {id:'trusted-rcc'},sendResponse);
    handler({type:'relay:nodeLabelNotify',eventId:13,conversationKey:OTHER},
      {id:'trusted-rcc'},sendResponse);
    assert.deepEqual(events,['bct:conversation-roster-changed']);
    assert.equal(replies[0].ok,true);
    assert.equal(replies[1].duplicate,true);
    assert.equal(replies[2].ok,false);
  });
  console.log('PASS 8 RCC FAVICON EVENT CONTRACT TESTS');
})().catch(e=>{console.error(e);process.exitCode=1});
