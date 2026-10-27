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
    this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.dataset={};this.children=[];this.attrs=new Map();this.isConnected=true;
    this.style={backgroundImage:"",backgroundColor:"",setProperty(name,value){this[name]=value}};
    const classes=new Set();
    this.classList={add:name=>classes.add(name),remove:name=>classes.delete(name),contains:name=>classes.has(name)};
    Object.defineProperty(this,"className",{get(){return [...classes].join(" ")},set(value){classes.clear();for(const name of value.split(/\s+/).filter(Boolean))classes.add(name)}});
  }
  append(...nodes){for(const node of nodes){this.children.push(node);node.parentElement=this}}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(node=>node!==this);this.isConnected=false}
  querySelectorAll(selector){const classes=selector.split(",").map(value=>value.trim().replace(/^\./,""));return this.children.filter(node=>classes.some(name=>node.classList.contains(name)))}
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
for(const className of ["monitor-desktop-thumb-window","monitor-thumb-v2-status","monitor-thumbnail-node-overlay"]){
  const child=document.createElement("span");child.className=className;visual.append(child);
}
let reply={ok:true,desktopId,wallpaper:{dataUri:"data:image/jpeg;base64,BOTTOM_LAYER",baseColor:"#107c10",baseProof:"windows-base-color"}};
let frameReads=0,decorations=0;
const policy=context.MonitorThumbnailLayerPolicy.create(context.MonitorThumbnailLayerPolicy.MODES.BACKGROUND_ONLY);
const renderer=context.MonitorDesktopThumbnailV2;
renderer.configure({
  visualSource:context.MonitorDesktopVisualSource.create({request:async()=>reply}),
  readFrame:async()=>{frameReads++;return null},
  afterWindowRender(){decorations++},
  layerPolicy:policy,
});

(async()=>{
  assert.equal(renderer.mode,"background-only");
  assert.equal(renderer.allowsLayer("background"),true);
  assert.equal(renderer.allowsLayer("windows"),false);
  assert.equal(renderer.allowsLayer("semantic"),false);
  assert.equal(renderer.allowsLayer("summary"),false);

  const first=await renderer.refresh(visual,desktopId,{forceWallpaper:true,includeWindows:true});
  assert.equal(first.wallpaperReady,true);
  assert.equal(first.frameReady,null,"disabled HWND layer must not enter frame capture");
  assert.equal(first.compositeReady,true);
  assert.equal(frameReads,0);
  assert.equal(decorations,0);
  assert.equal(visual.children.length,0,"background-only mode removes every child overlay from the visual");
  assert.match(visual.style.backgroundImage,/BOTTOM_LAYER/);
  assert.equal(visual.style.backgroundColor,"#107C10");
  assert.equal(visual.dataset.monitorThumbnailLayers,"background");

  reply={ok:false,desktopId,error:"NATIVE_TEMPORARY_FAILURE"};
  const failed=await renderer.refreshBackground(visual,desktopId,{force:true});
  assert.equal(failed.wallpaperReady,false,"retained pixels do not turn a failed read into acceptance");
  assert.equal(visual.dataset.wallpaperCapture,"retained");
  assert.match(visual.style.backgroundImage,/BOTTOM_LAYER/,"last accepted background survives a transient read failure");
  assert.match(visual.dataset.wallpaperFailureReason,/NATIVE_TEMPORARY_FAILURE/);

  reply={ok:true,desktopId,wallpaper:{mode:"solid",color:"#10893e",proof:"windows-solid-mode"}};
  assert.equal((await renderer.refreshBackground(visual,desktopId,{force:true})).wallpaperReady,true);
  assert.equal(visual.style.backgroundImage,"");
  assert.equal(visual.style.backgroundColor,"#10893E");
  assert.equal(visual.dataset.wallpaperAcceptedKind,"solid");

  reply={ok:false,desktopId,error:"SECOND_FAILURE"};
  assert.equal((await renderer.refreshBackground(visual,desktopId,{force:true})).wallpaperReady,false);
  assert.equal(visual.style.backgroundColor,"#10893E","last accepted solid color survives a later failure");

  assert.equal("inheritBackground" in renderer,false,
    "new desktops must read Windows truth instead of inheriting a source tile");
  console.log("PASS: background-only policy renders only exact wallpaper evidence and retains last-good photo/solid pixels without hiding failures");
})().catch(error=>{console.error(error);process.exitCode=1});
