"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const original=fs.readFileSync(path.join(__dirname,"../extension/monitor.js"),"utf8");
const start=original.indexOf("function beginMonitorBctNodePointerDrag(");
const end=original.indexOf("\nasync function commitMonitorBctNodeDrop(",start);
assert.ok(start>=0&&end>start);
function cl(){
 const s=new Set();
 return {add(...x){x.forEach(v=>s.add(v));},remove(...x){x.forEach(v=>s.delete(v));},contains(v){return s.has(v);}};
}
function emitter(){const m=new Map();return {m,addEventListener(k,v){m.set(k,v);},removeEventListener(k,v){if(m.get(k)===v)m.delete(k);},fire(k,e){m.get(k)?.(e);}};}
function fixture(){
 const ghost=[];
 function makeRow(key,x,y){
  let capture=false;
  const r={...emitter(),hidden:false,dataset:{conversationKey:key},classList:cl(),
   getBoundingClientRect(){return {left:x,right:x+80,top:y,bottom:y+30,width:80,height:30};},
   setPointerCapture(){capture=true;},hasPointerCapture(){return capture;},
   releasePointerCapture(id){capture=false;r.fire("lostpointercapture",{pointerId:id});}};
  return r;
 }
 const rows=[makeRow("first",0,40),makeRow("second",90,40),makeRow("third",0,80)];
 const list={hidden:false,dataset:{scopeId:"test"},classList:cl(),getBoundingClientRect:()=>({left:0,right:300,top:40,bottom:120,width:300,height:80}),querySelectorAll:()=>rows};
 const doc={...emitter(),documentElement:{classList:cl()},elementFromPoint:()=>({closest:(selector)=>selector===".monitor-bct-node-list"?list:null})};
 const win=emitter();
 const workers={contains:v=>v===list,querySelectorAll(selector){
  if(selector===".monitor-bct-node-list"||selector===".monitor-bct-node-list-available")return [list];
  if(selector===".monitor-bct-scope-heading")return [{getBoundingClientRect:()=>({left:0,right:300,top:0,bottom:30})}];
  if(selector===".monitor-bct-node-row.is-dragging")return rows;
  if(selector.includes("monitor-bct-drop-before"))return [...rows,list];
  return [];
 }};
 const commits=[];
 const ctx={monitorBctPointerDrag:null,monitorBctDraggedNodeKey:"",monitorBctSuppressedClickKey:"",monitorBctSuppressScopeClickUntil:0,monitorBctDragGhost:null,document:doc,window:win,monitorWorkers:workers,globalThis:{setTimeout:()=>1},Date,Math,String,Array,
  monitorBctNodeSelectionKey:n=>n.conversationKey,
  createMonitorNodeDragGhost(){const g={classList:cl(),style:{},removed:false,remove(){this.removed=true;}};ghost.push(g);return g;},
  moveMonitorNodeDragGhost(g,x,y){g.style.transform="translate3d("+x+"px,"+y+"px,0)";},
  commitMonitorBctNodeDrop(...a){commits.push(a);ctx.finishMonitorBctNodeDrag();}
 };
 vm.createContext(ctx);vm.runInContext(original.slice(start,end),ctx);
 function begin(){ctx.beginMonitorBctNodePointerDrag({button:0,pointerId:9,clientX:30,clientY:50},rows[0],{conversationKey:"dragged",nodeLabel:"N1",title:"First"});}
 function move(x,y){doc.fire("pointermove",{pointerId:9,clientX:x,clientY:y,preventDefault(){}});}
 function up(x,y){doc.fire("pointerup",{pointerId:9,clientX:x,clientY:y,preventDefault(){}});}
 function clean(){
  assert.equal(ctx.monitorBctPointerDrag,null);assert.equal(ctx.monitorBctDraggedNodeKey,"");
  assert.equal(rows[0].classList.contains("is-dragging"),false);
  assert.equal(doc.documentElement.classList.contains("monitor-bct-node-drag-active"),false);
  assert.equal(list.classList.contains("monitor-bct-node-list-target"),false);
  for(const r of rows){assert.equal(r.classList.contains("monitor-bct-drop-before"),false);assert.equal(r.classList.contains("monitor-bct-drop-after"),false);}
  assert.equal(ghost.at(-1)?.removed,true);
  for(const k of ["pointermove","pointerup","pointercancel"])assert.equal(doc.m.has(k),false);
  assert.equal(win.m.has("blur"),false);assert.equal(rows[0].m.has("lostpointercapture"),false);
 }
 return {ctx,rows,list,doc,win,ghost,commits,begin,move,up,clean};
}
for(const [x,key,place] of [[-12,"first","before"],[312,"second","after"]]){
 const f=fixture(), p=f.ctx.monitorBctNodeDropAt(x,55,"dragged");
 assert.equal(p?.targetConversationKey,key);assert.equal(p?.position,place);
 f.begin();f.move(x,55);f.up(x,55);
 assert.equal(f.commits.length,1);assert.equal(f.commits[0][1],key);assert.equal(f.commits[0][2],place);f.clean();
}
{
 const f=fixture();f.begin();f.move(-12,55);
 assert.equal(f.rows[0].classList.contains("monitor-bct-drop-before"),true);
 f.up(-90,55);assert.equal(f.commits.length,0);f.clean();
}
for(const [x,y] of [[-30,55],[340,55],[160,220],[160,-40]]){
 const f=fixture();assert.equal(f.ctx.monitorBctNodeDropAt(x,y,"dragged"),null);
}
{
 const f=fixture();assert.equal(f.ctx.monitorBctNodeDropAt(100,15,"dragged"),null);
 f.begin();f.move(150,55);f.up(250,90);
 assert.equal(f.commits.length,1);assert.equal(f.commits[0][1],"third");f.clean();
}
for(const kind of ["pointercancel","blur","lostpointercapture"]){
 const f=fixture();f.begin();f.move(120,55);
 if(kind==="blur")f.win.fire("blur",{});
 else if(kind==="lostpointercapture")f.rows[0].fire(kind,{pointerId:9});
 else f.doc.fire(kind,{pointerId:9});
 assert.equal(f.commits.length,0);f.clean();
}
assert.match(original,/if \(monitorBctPointerDrag\) cancelMonitorBctNodePointerDrag/);
assert.match(original,/document\.addEventListener\("pointerup", endMonitorBctNodePointerDrag, true\)/);
console.log(JSON.stringify({status:"PASS",cases:11,coverage:"edge-preview-drop,far-cancel,final-pointerup,quick-drag,blur,cancel,lostcapture,cleanup"}));