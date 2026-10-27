"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const names=[
  "monitor-thumbnail-contract.js",
  "monitor-desktop-visual-source.js",
  "monitor-thumbnail-layer-policy.js",
  "monitor-thumbnail-background-layer.js",
  "monitor-thumbnail-window-layer.js",
  "monitor-desktop-thumbnail-v2.js",
];
class Element {
  constructor(tag,doc){
    this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.dataset={};this.children=[];this.attrs=new Map();this.isConnected=true;this.textContent="";this.hidden=false;
    this.style={backgroundImage:"",backgroundColor:"",setProperty(name,value){this[name]=value}};
    const classes=new Set();
    this.classList={add:name=>classes.add(name),remove:name=>classes.delete(name),contains:name=>classes.has(name)};
    Object.defineProperty(this,"className",{get(){return [...classes].join(" ")},set(value){classes.clear();for(const name of value.split(/\s+/).filter(Boolean))classes.add(name)}});
  }
  append(...nodes){for(const node of nodes){this.children.push(node);node.parentElement=this}}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(node=>node!==this);this.isConnected=false}
  querySelectorAll(selector){const classes=selector.split(",").map(value=>value.trim().replace(/^\./,"").split("[")[0]);return this.children.filter(node=>classes.some(name=>node.classList.contains(name)))}
  setAttribute(name,value){this.attrs.set(name,String(value))}
  getAttribute(name){return this.attrs.get(name)??null}
  removeAttribute(name){this.attrs.delete(name)}
}
const document={createElement(tag){return new Element(tag,document)}};
const context={WeakMap,Map,Set,Object,Array,Number,String,Date,Promise,TypeError,globalThis:null};
context.globalThis=context;vm.createContext(context);
for(const name of names)vm.runInContext(fs.readFileSync(path.join(__dirname,"../extension",name),"utf8"),context);

const desktopId="8ac6b16f-820b-4773-89e7-276ae4b84040";
const visual=document.createElement("span");visual.className="monitor-desktop-thumb-visual";visual.dataset.desktopId=desktopId;
for(const className of ["monitor-thumbnail-node-overlay","monitor-window-status-layer","monitor-thumbnail-summary"]){
  const child=document.createElement("span");child.className=className;visual.append(child);
}
const pixels="data:image/jpeg;base64,REAL_WINDOW_PIXELS";
const frame={
  meta:{desktopId,previewVirtualLeft:0,previewVirtualTop:0,previewVirtualWidth:100,previewVirtualHeight:100,observedWindowHwnds:["101","102"]},
  frames:[
    {item:{hwnd:"101",left:5,top:10,width:60,height:50,z:0,cloaked:0,title:"Actual window"},captureState:"captured",physicalSource:"wgc-oneshot",dataUri:pixels,capturedAt:Date.now()},
    {item:{hwnd:"102",left:65,top:20,width:30,height:40,z:1,cloaked:2,title:"Unavailable"},captureState:"placeholder",physicalSource:"windows-native",dataUri:"",capturedAt:0},
  ]
};
let decorations=0;
const renderer=context.MonitorDesktopThumbnailV2;
renderer.configure({
  visualSource:context.MonitorDesktopVisualSource.create({request:async()=>({ok:true,desktopId,wallpaper:{mode:"solid",color:"#10893e",proof:"windows-solid-mode"}})}),
  readFrame:async()=>frame,
  afterWindowRender(){decorations++},
  layerPolicy:context.MonitorThumbnailLayerPolicy.create(context.MonitorThumbnailLayerPolicy.MODES.BACKGROUND_WINDOWS),
});

(async()=>{
  const result=await renderer.refresh(visual,desktopId,{forceWallpaper:true});
  assert.equal(renderer.mode,"background-windows");
  assert.equal(renderer.allowsLayer("background"),true);
  assert.equal(renderer.allowsLayer("windows"),true);
  assert.equal(renderer.allowsLayer("semantic"),false);
  assert.equal(renderer.allowsLayer("summary"),false);
  assert.equal(result.wallpaperReady,true);assert.equal(result.frameReady,true);assert.equal(result.compositeReady,true);
  assert.equal(decorations,0,"disabled semantic layer must not receive a decoration callback");
  assert.equal(visual.querySelectorAll(".monitor-thumbnail-node-overlay").length,0);
  assert.equal(visual.querySelectorAll(".monitor-window-status-layer").length,0);
  assert.equal(visual.querySelectorAll(".monitor-thumbnail-summary").length,0);
  const windows=visual.querySelectorAll(".monitor-desktop-thumb-window");
  assert.equal(windows.length,2);
  const captured=windows.find(node=>node.dataset.hwnd==="101");
  const failed=windows.find(node=>node.dataset.hwnd==="102");
  assert.equal(captured.getAttribute("src"),pixels);assert.equal(captured.style.display,"block");
  assert.equal(failed.getAttribute("src"),null);assert.equal(failed.style.display,"none");
  assert.equal(visual.style.backgroundColor,"#10893E");
  assert.equal(visual.dataset.monitorThumbnailLayers,"background,windows");
  console.log("PASS: staged thumbnail renders only the accepted background and real WGC window pixels; semantic, summary, and failed-capture visuals stay absent");
})().catch(error=>{console.error(error);process.exitCode=1});
