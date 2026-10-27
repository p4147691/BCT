"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const ext=path.join(__dirname,"..","extension");
const source=fs.readFileSync(path.join(ext,"monitor-thumbnail-interaction-layer.js"),"utf8");
const compositor=fs.readFileSync(path.join(ext,"monitor-desktop-thumbnail-v2.js"),"utf8");
const bootstrap=fs.readFileSync(path.join(__dirname,"..","source-parts","05-native-lifecycle.js"),"utf8");
assert.match(compositor,/interactionLayer\?\.reconcile\(target,id\)/,"V2 must reconcile input after a HWND frame render");
assert.match(bootstrap,/BACKGROUND_WINDOWS_INTERACTION/,"accepted runtime mode must enable interaction without semantic overlays");
assert.match(bootstrap,/moveWindow:\s*\(\{hwnd,sourceDesktopId,targetDesktopId\}\)/,"runtime must inject one exact-HWND move port");
assert.doesNotMatch(source,/monitorNative|connectNative|moveWindowToDesktop|backgroundImage\s*=|backgroundColor\s*=|\.src\s*=/);

class Classes{
  constructor(){this.values=new Set();}
  add(...names){for(const name of names)this.values.add(name);}
  remove(...names){for(const name of names)this.values.delete(name);}
  contains(name){return this.values.has(name);}
  from(value){this.values=new Set(String(value||"").split(/\s+/).filter(Boolean));}
  text(){return [...this.values].join(" ");}
}
class Element{
  constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.dataset={};this.children=[];this.parentElement=null;this.style={};this.classList=new Classes();this.listeners=new Map();this.draggable=true;}
  set className(value){this.classList.from(value);}get className(){return this.classList.text();}
  append(node){this.children.push(node);node.parentElement=this;}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(x=>x!==this);this.parentElement=null;}
  contains(node){for(let item=node;item;item=item.parentElement)if(item===this)return true;return false;}
  closest(selector){const cls=String(selector).replace(/^\./,"");for(let node=this;node;node=node.parentElement)if(node.classList.contains(cls))return node;return null;}
  querySelectorAll(selector){const want=String(selector).split("[")[0].replace(/^\./,"");const out=[];const visit=node=>{for(const child of node.children){if(child.classList.contains(want))out.push(child);visit(child);}};visit(this);return out;}
  addEventListener(type,fn){const list=this.listeners.get(type)||[];list.push(fn);this.listeners.set(type,list);}
  removeEventListener(type,fn){this.listeners.set(type,(this.listeners.get(type)||[]).filter(x=>x!==fn));}
  emit(type,event){for(const fn of this.listeners.get(type)||[])fn(event);}
  getBoundingClientRect(){return {width:80,height:45};}
  setPointerCapture(){} releasePointerCapture(){}
}
class EventHub{
  constructor(){this.listeners=new Map();}
  addEventListener(type,fn){const list=this.listeners.get(type)||[];list.push(fn);this.listeners.set(type,list);}
  removeEventListener(type,fn){this.listeners.set(type,(this.listeners.get(type)||[]).filter(x=>x!==fn));}
  emit(type,event){for(const fn of [...(this.listeners.get(type)||[])])fn(event);}
}
const win=new EventHub(),scheduled=[];
const doc=new EventHub();doc.defaultView=win;doc.currentHit=null;doc.elementFromPoint=()=>doc.currentHit;
doc.createElement=tag=>new Element(tag,doc);doc.body=doc.createElement("body");
doc.querySelectorAll=selector=>doc.body.querySelectorAll(selector);
const D1="8ac6b16f-820b-4773-89e7-276ae4b84040",D2="c991b275-7933-4697-9d6e-73bf31ae4379";
function desktop(id){const tile=doc.createElement("button");tile.className="monitor-desktop-thumb";tile.dataset.desktopId=id;const visual=doc.createElement("span");visual.className="monitor-desktop-thumb-visual";visual.dataset.desktopId=id;tile.append(visual);doc.body.append(tile);return {tile,visual};}
const first=desktop(D1),second=desktop(D2),image=doc.createElement("img");image.className="monitor-desktop-thumb-window";image.dataset.hwnd="123";first.visual.append(image);
const moves=[];
const context={globalThis:null,WeakMap,Map,Set,Object,Array,Number,String,Math,TypeError,setTimeout:fn=>{scheduled.push(fn);return scheduled.length}};
context.globalThis=context;vm.createContext(context);vm.runInContext(source,context);
const layer=context.MonitorThumbnailInteractionLayer.create({
  contract:{isDesktopId:value=>/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(String(value||""))},
  moveWindow:async payload=>{moves.push(payload);return true;},feedbackMs:650
});
const pointer=(extra={})=>({button:0,pointerId:7,clientX:5,clientY:5,preventDefault(){},stopPropagation(){},...extra});
assert.equal(layer.reconcile(first.visual,D1),true);
assert.equal(image.dataset.monitorDragBound,"1");
assert.equal(image.draggable,false);
image.emit("pointerdown",pointer());
doc.currentHit=second.tile;doc.emit("pointermove",pointer({clientX:40,clientY:30}));
assert.equal(layer.dragging,true);assert(image.classList.contains("monitor-window-dragging"));
assert(second.tile.classList.contains("monitor-desktop-drop-target"));
assert.equal(doc.body.querySelectorAll(".monitor-thumbnail-window-drag-ghost").length,1);
doc.emit("pointerup",pointer({clientX:40,clientY:30}));
setImmediate(()=>{
  assert.equal(layer.dragging,false);assert.equal(moves.length,1);
  assert.deepEqual(JSON.parse(JSON.stringify(moves[0])),{hwnd:"123",sourceDesktopId:D1,targetDesktopId:D2});
  assert.equal(doc.body.querySelectorAll(".monitor-thumbnail-window-drag-ghost").length,0);
  assert(second.tile.classList.contains("monitor-desktop-drop-success"));
  for(const fn of scheduled.splice(0))fn();
  assert(!second.tile.classList.contains("monitor-desktop-drop-pending"));
  console.log("PASS: independent thumbnail interaction binds exact HWND drag, ghost, target and one injected desktop move without pixel ownership");
});
