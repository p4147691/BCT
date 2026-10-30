"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null,Map,Set,Array,Number,String,Math,Date,Promise};
ctx.globalThis=ctx;vm.createContext(ctx);
const source=fs.readFileSync(path.join(root,"extension/monitor-desktop-strip-view.js"),"utf8");
vm.runInContext(source,ctx);
const bundle=fs.readFileSync(path.join(root,"extension/monitor.js"),"utf8");
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
assert(html.indexOf('src="monitor-desktop-strip-view.js"')<html.indexOf('src="monitor.js"'));
assert.match(bundle,/MonitorDesktopStripView[.]create/);
assert.doesNotMatch(source,/monitorNative|chrome[.]|monitorDesktopState|monitorDesktopThumbs/);
function element(tag){
 const el={tag,dataset:{},children:[],listeners:new Map(),hidden:false,isConnected:true,parentElement:null,className:"",
  classSet:new Set(),append(...kids){kids.forEach(k=>{k.parentElement=this;this.children.push(k)})},
  querySelector(q){return this.querySelectorAll(q)[0]||null},
  querySelectorAll(q){const cls=(q.split(".").pop()||"").split("[")[0],out=[];const visit=e=>{for(const c of e.children){if(c.className.split(" ").includes(cls))out.push(c);visit(c)}};visit(this);return out},
  addEventListener(name,fn){this.listeners.set(name,fn)},
  setAttribute(name,value){this[name]=String(value)},
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(x=>x!==this)},
  insertBefore(k,before){k.parentElement=this;const i=this.children.indexOf(before);this.children.splice(i<0?this.children.length:i,0,k)}
 };
 el.classList={add:n=>el.classSet.add(n),remove:n=>el.classSet.delete(n),
   toggle:(n,on)=>on?el.classSet.add(n):el.classSet.delete(n)};
 return el;
}
const doc={createElement:element},strip=element("div"),calls={native:[],preview:[],render:[],background:[],management:[],drag:[],frame:0,badges:0,scroll:0};
const state={count:2,currentIndex:0,selectedIndex:0,desktopIds:["D1-uuid","D2-uuid"]};
const ports={
 desktopState:()=>state,attachManagement:(element,id)=>calls.management.push(id),
 beginDrag:ev=>calls.drag.push(ev),preview:index=>calls.preview.push(index),
 switchDesktop:async index=>{calls.native.push(index);return {ok:true,currentIndex:index}},
 renderDesktops:state=>calls.render.push(state),
 status:()=>{},bindDrop:()=>{},deletedUndo:()=>null,deletedUndoExpiresAt:()=>0,undoDelete:()=>{},
 thumbnail:()=>({refreshBackground:async (_visual,id)=>{calls.background.push(id)},
    allowsLayer:()=>true}),syncBadges:()=>calls.badges++,
 syncScrollArrows:()=>calls.scroll++,frame:cb=>{calls.frame++;cb()},after:fn=>fn()
};
(async()=>{
 const controller=ctx.MonitorDesktopStripView.create({root:strip,document:doc,ports});
 controller.sync();
 assert.equal(strip.children.length,2);
 assert.equal(strip.children[0].dataset.desktopId,"D1-uuid");
 assert.equal(strip.children[1].dataset.desktopId,"D2-uuid");
 assert.equal(strip.children[0].querySelector(".monitor-desktop-number-badge").textContent,"D1");
 assert.equal(strip.children[1].querySelector(".monitor-desktop-number-badge").textContent,"D2");
 assert.deepEqual(calls.background,["D1-uuid","D2-uuid"]);
 strip.children[1].listeners.get("click")({preventDefault(){},stopPropagation(){}});
 assert.deepEqual(calls.preview,[1]);
 await strip.children[1].listeners.get("dblclick")({preventDefault(){}});
 assert.deepEqual(calls.native,[1]);
 assert.equal(calls.render.length,1);
 assert.deepEqual(calls.preview,[1,1]);
 const old=strip.children[0];
 state.desktopIds=["D2-uuid","D3-uuid"];state.selectedIndex=1;state.currentIndex=1;
 controller.sync();
 assert.equal(strip.children.length,2);
 assert.equal(strip.children.includes(old),false);
 assert.equal(strip.children[0].dataset.desktopId,"D2-uuid");
 assert.equal(strip.children[1].dataset.desktopId,"D3-uuid");
 assert.equal(strip.children[1].classSet.has("selected"),true);
 assert.equal(calls.background.at(-1),"D3-uuid");
 assert.throws(()=>ctx.MonitorDesktopStripView.create({}),/PORTS_REQUIRED/);
 console.log("PASS: DesktopStrip DOM card owner, exact GUID, create/remove, selection, native switch port and V2 background");
})().catch(e=>{console.error(e);process.exitCode=1});
