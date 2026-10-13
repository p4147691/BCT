const fs=require('fs');
const vm=require('vm');
const {randomUUID}=require('crypto');
const assert=require('assert');
const bg=fs.readFileSync('background.js','utf8');
const content=fs.readFileSync('content.js','utf8');
const source=bg+'\n;globalThis.__renameTest={resolveExactConversationCommand};';
let tabs=[{id:7,windowId:1,title:'Same title',url:'https://chatgpt.com/c/target-key'}];
const store={registrations:{},settings:{token:'t',armed:false,budget:0,instanceId:'instance1234'},pending:{},results:[],processed:[]};
const port={onMessage:{addListener(){}},onDisconnect:{addListener(){}},postMessage(){}};
const context={console,URL,setTimeout,clearTimeout,setInterval:()=>0,crypto:{randomUUID},RelayCore:{conversationKey:(u)=>{try{return new URL(u).pathname.match(/\/c\/([a-z0-9-]+)/i)?.[1]||''}catch{return''}},normalizeRole:(v)=>String(v||'').toUpperCase()},chrome:{storage:{local:{get:async()=>store,set:async(p)=>Object.assign(store,p)}},tabs:{query:async()=>tabs,get:async(id)=>{const t=tabs.find(x=>x.id===Number(id));if(!t)throw Error('tab not found');return t},sendMessage:async()=>({ok:true})},windows:{get:async()=>({})},scripting:{executeScript:async()=>[]},runtime:{id:'x',onMessage:{addListener(){}},connectNative:()=>port,onStartup:{addListener(){}},onInstalled:{addListener(){}}}}};
vm.createContext(context); vm.runInContext(source,context);
(async()=>{
 const fn=context.__renameTest.resolveExactConversationCommand;
 const ok=await fn({conversationKey:'target-key',tabId:7,sessionId:''}); assert.strictEqual(ok.id,7);
 await assert.rejects(()=>fn({conversationKey:'other-key',tabId:7,sessionId:''}),/target mismatch/);
 await assert.rejects(()=>fn({conversationKey:'target-key',tabId:7,sessionId:'wrong-session'}),/session mismatch/);
 const hs=content.indexOf('function exactConversationUiAnchor'); const he=content.indexOf('async function waitForRenameUi',hs); assert(hs>=0&&he>hs);
 const helper=content.slice(hs,he); assert(helper.includes('[data-sidebar-item="true"]')); assert(helper.includes('rect.bottom > 0')); assert(helper.includes("aria-current")); assert(helper.includes("data-state=\"active\"")); assert(helper.includes('return pool[0]')); assert(helper.includes('RENAME_TARGET_NOT_FOUND'));
 const start=content.indexOf('async function renameConversationUi'); const end=content.indexOf('async function beginRelayExecution',start); assert(start>=0&&end>start);
 const body=content.slice(start,end); assert(body.includes('currentConversationKey() !== key')); assert(body.includes('openConversationRenameInput(key)')); assert(body.includes("input.closest('[role=\"dialog\"]')")); assert(body.includes('setRenameInputValue(input, title)')); assert(body.includes('verifyConversationRenameUi(key, title)')); assert(body.includes('RENAME_UI_NOT_ACCEPTED')); assert(body.includes('requestSubmit')); assert(body.includes("button.type === 'submit'")); assert(body.includes("savedTitle: title")); assert(!body.includes('document.title'));
 console.log('conversation rename tests: PASS');
})().catch(e=>{console.error(e);process.exitCode=1});

