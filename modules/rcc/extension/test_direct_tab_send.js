const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { randomUUID } = require('crypto');
const source = fs.readFileSync('modules/rcc/extension/background.js', 'utf8');
const sessionId = '786b7b6b9671446f85497e097111e5ec';
const instanceId = '6174664e1c1b4e6db1d4729c841db3c9';
const conversation = '6ad4bb5d-6624-83ee-b045-e57fdad5120e';
const tabs = [
  {id:594834261,windowId:594834176,url:'https://chatgpt.com/',title:'ChatGPT'},
  {id:594834262,windowId:594834176,url:'https://chatgpt.com/',title:'ChatGPT'},
  {id:594834177,windowId:594834176,url:'https://chatgpt.com/c/'+conversation,title:'History'}
];
const store = {registrations:{},settings:{instanceId,armed:false,budget:0},pending:{},operations:{},results:[],processed:[]};
const msgs = [];
const port = {onMessage:{addListener(){}},onDisconnect:{addListener(){}},postMessage(x){msgs.push(x)}};
const chrome = {
 storage:{local:{get:async()=>store,set:async update=>Object.assign(store,update)}},
 tabs:{
   get:async id=>{const t=tabs.find(x=>x.id===Number(id));if(!t)throw Error('missing');return t;},
   query:async()=>tabs, sendMessage:async()=>({ok:true}), create:async()=>{throw Error('UNEXPECTED_CREATE')},
   onCreated:{addListener(){}},onUpdated:{addListener(){}},onRemoved:{addListener(){}}
 },
 scripting:{executeScript:async()=>{}},
 runtime:{id:'mock',connectNative:()=>port,onMessage:{addListener(){}},onStartup:{addListener(){}},onInstalled:{addListener(){}}}
};
const ctx={console,URL,crypto:{randomUUID},setTimeout:()=>0,clearTimeout:()=>{},setInterval:()=>0,clearInterval:()=>{},chrome,
RelayCore:{normalizeRole:x=>String(x).trim().toUpperCase(),
conversationKey:url=>(String(url).match(/\/c\/([a-f0-9-]{36})/)||[])[1]||'',makeResultEnvelope:()=>''}};
vm.createContext(ctx);
vm.runInContext(source,ctx);
vm.runInContext("endpointSessionId='"+sessionId+"';",ctx);
const delivered=[];
ctx.dispatchRelay = async options=>{
  delivered.push({...options});
  return {ok:true,deliveryConfirmed:true};
};
async function invoke(i,id,key='',win=594834176,inst=instanceId,work='BCT-TEMP-MANAGER-SEND-TAB-20261019-01'){
return ctx.sendToExistingTab({operationId:id,instanceId:inst,sessionId,workId:work,
tabId:i,windowId:win,conversationKey:key,text:'bounded test instruction'});
}
(async()=>{
  const wrong=await invoke(594834261,'wrong-win','',9999);
  throw Error('unreachable:'+wrong);
})().catch(async e=>{
  // A mismatched window must refuse before a registration or send.
  assert.match(String(e),/DIRECT_TAB_IDENTITY_MISMATCH/);
  assert.equal(delivered.length,0);
  let x=await invoke(594834261,'m-once');
  assert.equal(x.result.state,'SUBMITTED');
  assert.equal(x.result.tabId,594834261);
  assert.equal(delivered.length,1);
  const again=await invoke(594834261,'m-once');
  assert.equal(again.replayed,true);
  assert.equal(delivered.length,1,'idempotent replay must not re-send');
  const other=await invoke(594834262,'i-once');
  assert.equal(other.result.state,'SUBMITTED');
  assert.equal(delivered.length,2);
  const history=await invoke(594834177,'history-once',conversation);
  assert.equal(history.result.state,'SUBMITTED');
  assert.equal(delivered.length,3);
  await assert.rejects(()=>invoke(594834177,'bad-key','00000000-0000-0000-0000-000000000000'),/DIRECT_TAB_CONVERSATION_MISMATCH/);
  assert.equal(delivered.length,3);
  await assert.rejects(()=>invoke(594834177,'not-owner',conversation,594834176,instanceId,'WRONG-WORK'),/DIRECT_TAB_ROLE_ALREADY_OWNED/);
  assert.equal(delivered.length,3);
  assert.equal(store.registrations['BCT_TAB_594834261'].authorization,'ACT_CONVERSATION_BOOTSTRAP');
  assert.equal(store.registrations['BCT_TAB_594834177'].authorization,'ACT_CONVERSATION_BIND');
  assert.ok(Object.values(store.registrations).every(x=>x.directTabWorkId==='BCT-TEMP-MANAGER-SEND-TAB-20261019-01'));
  console.log('RCC_DIRECT_TAB_TEST_PASS cases=8 sends='+delivered.length);
}).catch(e=>{console.error(e);process.exit(1)});
