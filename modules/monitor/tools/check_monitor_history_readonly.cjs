'use strict';
const assert = require('node:assert/strict');
const api = require('../extension/monitor-history-readonly.js');
function payload() {
  return {
    schema: 'BCT_MONITOR_HISTORY_VIEW_V1', source: 'IMMUTABLE_SQLITE_SNAPSHOT',
    snapshot_only: true,
    current: {nodes:[{node_id:'n1',name:'Current AI',role:'WORKER'}]},
    history: {
      nodes:[{node_id:'n0',session_count:2,historical_name:null}],
      works:[{work_id:'W1',session_count:1,operation_count:4}],
      projects:[{project_id:'P1',conversation_keys:['c1']}]
    },
    full_history_verified:false, conversation_coverage:'NOT_VERIFIED'
  };
}
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.events={}; this.attributes={}; this._text=''; }
  set textContent(value) { this._text=String(value);this.children=[]; }
  get textContent() { return this._text+this.children.map(x=>x.textContent).join(''); }
  append(...items) { this.children.push(...items); }
  appendChild(el) { this.children.push(el); }
  addEventListener(name,callback) { this.events[name]=callback; }
  setAttribute(k,v) { this.attributes[k]=v; }
  remove() { this.removed=true; }
  click() { return this.events.click(); }
}
const doc={createElement:tag=>new Element(tag)};
function test(name,fn) { tests.push({name,fn}); }
const tests=[];
test('valid source with explicit unknown coverage',()=> {
 const m=api.model(payload());
 assert.equal(m.state,'READY');
 assert.equal(m.coverage,'NOT_VERIFIED');
});
test('rejects unverified FULL',()=> {
 const p=payload(); p.conversation_coverage='FULL';
 assert.equal(api.model(p).state,'UNAVAILABLE');
});
test('rejects wrong source and incomplete arrays',()=> {
 const p=payload();p.source='LIVE_DB';
 assert.equal(api.model(p).state,'UNAVAILABLE');
 assert.equal(api.model({}).state,'UNAVAILABLE');
});
test('user click only and separate sections',async()=> {
 let calls=0; const view=api.mount({document:doc,loadSnapshot:async()=>{calls++;return payload();}});
 assert.equal(calls,0);
 const buttons=view.element.children[0].children;
 await buttons[0].click();
 assert.equal(calls,1);
 assert.match(view.element.textContent,/현재 등록 노드/);
 assert.doesNotMatch(view.element.textContent,/과거 프로젝트·노드 기록/);
 await buttons[1].click();
 assert.equal(calls,2);
 assert.match(view.element.textContent,/과거 프로젝트·노드 기록/);
 assert.match(view.element.textContent,/과거 이름\/역할: 미확정/);
 view.dispose();
 assert.equal(view.element.removed,true);
});
test('network error cannot be confused with empty result',async()=> {
 const v=api.mount({document:doc,loadSnapshot:()=>Promise.reject(Error('offline'))});
 await v.refresh('history');
 assert.match(v.element.textContent,/조회 실패/);
 assert.doesNotMatch(v.element.textContent,/기록 없음/);
});
test('untrusted text never interpreted as markup',async()=> {
 const p=payload();p.history.works[0].work_id='<img src=x onerror=alert(1)>';
 const v=api.mount({document:doc,loadSnapshot:async()=>p});
 await v.refresh('history');
 assert.match(v.element.textContent,/<img src=x/);
 assert.equal(v.element.children[1].children.every(c=>c.tag==='p'),true);
});
(async()=>{
 for(const t of tests) {
   await t.fn();
   process.stdout.write('PASS '+t.name+'\n');
 }
 process.stdout.write(tests.length+' monitor history tests PASS\n');
})().catch(err=>{console.error(err);process.exitCode=1;});
