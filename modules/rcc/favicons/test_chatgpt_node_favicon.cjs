'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const src = fs.readFileSync(path.join(__dirname,'chatgpt-node-favicon.user.js'),'utf8');
const A='6ae269f6-130c-83ee-9384-dffa2d2a946d'; // N70
const B='6ae295f6-8090-83e8-b444-02d46f637c20'; // N71
function row(uuid,label,extra={}) {
  return {conversation_key:uuid,node_label:label,tab_id:71,window_id:22,
    presence:'OPEN',url:'https://chatgpt.com/c/'+uuid,...extra};
}
function fixture(start='/c/'+A,{deferred=false}={}) {
  const listeners={}; let requestCount=0, pending=[];
  const original={rel:'icon',href:'original.ico',isConnected:true};
  let last=original; let nodes=[original], observer=null;
  let tabs=[row(A,'N70')]; let payloadState='MATCH', httpStatus=200, malformed=false;
  const head={
    get lastElementChild(){return last;},
    append(link){if(!nodes.includes(link))nodes.push(link);link.isConnected=true;last=link;
      // actual MutationObserver notifications are asynchronous in browsers
    }
  };
  function makeLink() {
    return {href:'',isConnected:false,hasAttribute:false,rel:'',type:'',sizes:'',
      setAttribute(){this.hasAttribute=true;},
      remove(){this.isConnected=false;if(last===this)last=original;}
    };
  }
  function makeCanvas() {
    const drawn=[];
    return {width:0,height:0,getContext(){return {
      beginPath(){},roundRect(){},fill(){},stroke(){},fillText(text){drawn.push(text);},
      set fillStyle(_) {},set strokeStyle(_) {},set lineWidth(_) {},
      set textAlign(_) {},set textBaseline(_) {},set font(_) {}
    }},toDataURL(type){assert.equal(type,'image/png');return 'data:image/png;base64,'+Buffer.from(drawn.join('|')).toString('base64');}};
  }
  const document={head,title:'기존 ChatGPT 제목',hidden:false,
    createElement(tag){return tag==='canvas'?makeCanvas():makeLink();},
    querySelectorAll(selector){
      assert.match(selector,/data-bct-node-favicon-v1/);
      return nodes.filter(n=>n.isConnected&&n.hasAttribute);
    },
    addEventListener(name,fn){listeners['doc:'+name]=fn;}
  };
  const window={navigation:{addEventListener(name,fn){listeners['nav:'+name]=fn;}},
    addEventListener(name,fn){listeners[name]=fn;},
    setInterval(){throw Error('PERIODIC_POLLING_FORBIDDEN');}};
  const location={pathname:start};
  const ctx={document,window,location,MutationObserver:class{constructor(fn){observer=fn;}observe(){}},
    queueMicrotask:fn=>fn(),GM_xmlhttpRequest(args){
      requestCount++;
      const reply=()=>{
        const payload={rcc:{instances:[{tabs}],payload:{state:payloadState}}};
        args.onload({status:httpStatus,responseText:malformed?'?':JSON.stringify(payload)});
      };
      if(deferred)pending.push(reply);else reply();
    }
  };
  vm.runInNewContext(src,ctx,{timeout:1200});
  const active=()=>nodes.filter(n=>n.isConnected&&n.hasAttribute)[0]||null;
  return {
    listeners,document,location,window,original,signal(name){assert.ok(listeners[name],'listener '+name);listeners[name]();},
    flush(){assert.ok(pending.length);pending.shift()();},
    setRows(v){tabs=v;},setPayloadState(v){payloadState=v;},setStatus(v){httpStatus=v;},
    malformed(){malformed=true;},headChange(){if(observer)observer();},
    get requestCount(){return requestCount;},
    get icon(){const l=active();return l?Buffer.from(l.href.split(',')[1],'base64').toString():null;},
    get ownLink(){return active();},
    get originalPreserved(){return original.isConnected&&original.href==='original.ico';}
  };
}
function check(cond,name){cond();console.log('PASS '+name);}
check(()=>{
  const f=fixture();assert.equal(f.icon,'N|70');assert.equal(f.document.title,'기존 ChatGPT 제목');
  assert.equal(f.originalPreserved,true);assert.equal(f.requestCount,1);
},'initial exact N70 PNG, title and original icon unchanged');
check(()=>{
  const f=fixture();f.setRows([row(A,'N71')]);f.signal('bct:conversation-roster-changed');
  assert.equal(f.icon,'N|71');
},'roster event revalidates node registration');
check(()=>{
  const f=fixture();f.setRows([]);f.signal('bct:conversation-roster-changed');
  assert.equal(f.icon,null);assert.equal(f.originalPreserved,true);
},'unregistered conversation restores original');
check(()=>{
  const f=fixture();f.setRows([row(A,'N70'),row(A,'N70',{tab_id:72})]);
  f.signal('focus');assert.equal(f.icon,null);
},'duplicated same-UUID tabs fail closed');
check(()=>{
  const f=fixture();f.setRows([row(A,'N71',{url:'https://chatgpt.com/c/'+B})]);
  f.signal('focus');assert.equal(f.icon,null);
},'URL and identity mismatch fail closed');
check(()=>{
  const f=fixture();f.setRows([row(A,'N71',{presence:'CLOSED'})]);
  f.signal('focus');assert.equal(f.icon,null);
},'closed identity fails closed');
check(()=>{
  const f=fixture();f.setPayloadState('SOURCE_MISSING');f.signal('focus');assert.equal(f.icon,null);
},'broken Core/RCC source fails closed');
check(()=>{
  const f=fixture();f.setStatus(503);f.signal('focus');assert.equal(f.icon,null);
},'transport error restores the original icon');
check(()=>{
  const f=fixture('/');assert.equal(f.icon,null);assert.equal(f.requestCount,0);
  f.setRows([row(B,'N71')]);f.location.pathname='/c/'+B;f.signal('nav:currententrychange');
  assert.equal(f.icon,'N|71');
},'new tab home to conversation via Navigation API');
check(()=>{
  const f=fixture();f.setRows([row(B,'N71')]);f.location.pathname='/c/'+B;f.signal('nav:currententrychange');
  assert.equal(f.icon,'N|71');f.location.pathname='/';f.signal('popstate');assert.equal(f.icon,null);
},'SPA switch then leave conversation');
check(()=>{
  const f=fixture();f.setRows([row(A,'N71')]);f.signal('focus');
  assert.equal(f.icon,'N|71');
  f.document.hidden=true;f.signal('pageshow');
  assert.equal(f.icon,'N|71');
},'tab move and focus refresh without periodic timers');
check(()=>{
  const f=fixture('/c/'+A,{deferred:true});
  assert.equal(f.requestCount,1);
  f.location.pathname='/c/'+B;f.setRows([row(B,'N71')]);f.signal('nav:currententrychange');
  f.flush();assert.equal(f.icon,null);assert.equal(f.requestCount,2);
  f.flush();assert.equal(f.icon,'N|71');
},'inflight navigation race never paints stale node');
check(()=>{
  const f=fixture();f.document.head.append({}); // simulation: ChatGPT modifies head after icon
  f.headChange();assert.equal(f.document.head.lastElementChild,f.ownLink);
  assert.equal(f.document.title,'기존 ChatGPT 제목');
},'ChatGPT head changes preserve favicon priority and title');
check(()=>{
  assert.doesNotMatch(src,/setInterval\s*\(/);
  assert.doesNotMatch(src,/document\.title\s*=/);
  assert.doesNotMatch(src,/chrome\.runtime\.sendMessage\s*\(/);
},'no 15-30 second polling, title writes or RCC message effects');
console.log('ALL 14 FAVICON ISOLATED REGRESSIONS PASS');
