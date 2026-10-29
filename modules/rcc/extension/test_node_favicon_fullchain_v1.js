'use strict';
// Real RCC notifier + real RCC content router + PR352 userscript in isolated JS VMs.
// This exercises the event chain; source events/operation receipts are tested in Python.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const UUID='6ae269f6-130c-83ee-9384-dffa2d2a946d';
const OTHER='6ae295f6-8090-83e8-b444-02d46f637c20';
const INSTANCE='a'.repeat(32),SESSION='b'.repeat(32);
const source=rel=>fs.readFileSync(path.join(__dirname,rel),'utf8');
const userSource=fs.readFileSync(path.join(__dirname,'../favicons/chatgpt-node-favicon.user.js'),'utf8');

const original={rel:'icon',href:'original.ico',isConnected:true};
const own=[];const listeners={};
let last=original,uuid=UUID,node='N70',requests=0,contentListener;
let hidden=true;
const head={
  get lastElementChild(){return last;},
  append(link){link.isConnected=true;last=link;if(!own.includes(link))own.push(link);}
};
const document={
  head,get hidden(){return hidden;},
  get title(){return 'Original chat title';},
  querySelectorAll:()=>own.filter(x=>x.isConnected&&x.mine),
  createElement:tag=>{
    if(tag==='canvas') {
      const text=[];
      return {width:0,height:0,getContext:()=>({
        beginPath(){},roundRect(){},fill(){},stroke(){},
        fillText(t){text.push(t);},
        set fillStyle(x){},set strokeStyle(x){},set lineWidth(x){},
        set textAlign(x){},set textBaseline(x){},set font(x){}
      }),toDataURL:()=>'data:image/png;base64,'+Buffer.from(text.join('|')).toString('base64')};
    }
    return {isConnected:false,href:'',setAttribute(){this.mine=true;},
      remove(){this.isConnected=false;if(last===this)last=original;}};
  },
  addEventListener(name,fn){listeners['doc:'+name]=fn;}
};
const location={pathname:'/c/'+UUID};
const win={
  addEventListener(name,fn){listeners[name]=fn;},
  dispatchEvent(event){listeners[event.type]?.();},
  navigation:{addEventListener(name,fn){listeners['nav:'+name]=fn;}}
};
const contentContext=vm.createContext({
  chrome:{runtime:{id:'test-rcc',onMessage:{addListener:fn=>{contentListener=fn}}}},
  document,location,window:win,
  Event:class{constructor(type){this.type=type}},
  currentConversationKey:()=>uuid,
  queueMicrotask:fn=>fn(),MutationObserver:class{observe(){}},
  GM_xmlhttpRequest:({onload})=>{
    requests++;
    onload({status:200,responseText:JSON.stringify({rcc:{
      payload:{state:'MATCH'},instances:[{tabs:node?[{
        conversation_key:uuid,node_label:node,tab_id:71,window_id:22,
        presence:'OPEN',url:'https://chatgpt.com/c/'+uuid
      }]:[]}]}})});
  }
});
vm.runInContext(userSource,contentContext);
vm.runInContext(source('content/content_router.js'),contentContext);
const chromeTab={id:71,windowId:22,url:'https://chatgpt.com/c/'+UUID};
const rccContext=vm.createContext({
  endpointSessionId:SESSION,
  loadState:async()=>({settings:{instanceId:INSTANCE}}),
  browserGateway:{
    getExactTab:async()=>chromeTab,
    sendWithReceiver:async(_tab,msg)=>{
      let ack;
      contentListener(msg,{id:'test-rcc'},result=>ack=result);
      return ack;
    }
  },
  getChatTabs:async()=>[chromeTab],
  isChatTab:t=>t?.url?.startsWith('https://chatgpt.com/'),
  RelayCore:{conversationKey:url=>/\/c\/([a-f0-9-]{36})/.exec(url)?.[1]||''}
});
vm.runInContext(source('domain/node_favicon_notify_service.js'),rccContext);
const send=vm.runInContext('notifyNodeFaviconChanged',rccContext);
const command=(eventId)=>({
  eventId,conversationKey:uuid,tabId:71,windowId:22,
  instanceId:INSTANCE,sessionId:SESSION
});
const rendered=()=>{
  const link=own.find(x=>x.isConnected);
  return link?Buffer.from(link.href.split(',')[1],'base64').toString():'DEFAULT';
};
(async()=>{
  assert.equal(rendered(),'N|70');
  assert.equal(hidden,true);
  node='N71';
  let reply=await send(command(101),'node-label.101.71');
  assert.equal(reply.ok,true);assert.equal(rendered(),'N|71');
  assert.equal(document.title,'Original chat title');
  assert.equal(original.isConnected,true);
  const before=requests;
  reply=await send(command(101),'node-label.101.71');
  assert.equal(reply.duplicate,true);assert.equal(requests,before);
  node=null;
  reply=await send(command(102),'node-label.102.71');
  assert.equal(reply.ok,true);assert.equal(rendered(),'DEFAULT');
  node='N70';reply=await send(command(103),'node-label.103.71');
  assert.equal(reply.ok,true);assert.equal(rendered(),'N|70');
  uuid=OTHER;location.pathname='/c/'+OTHER;
  assert.equal((await send(command(104),'node-label.104.71')).ok,false);
  assert.equal(requests,before+2);
  console.log('PASS FULLCHAIN: RCC exact background tab -> content event -> real PR352 renderer N70/N71/unregistered, no polling or title change');
})().catch(e=>{console.error(e);process.exitCode=1});
