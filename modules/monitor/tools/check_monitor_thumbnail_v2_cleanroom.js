"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const modules=[
  "monitor-thumbnail-contract.js",
  "monitor-desktop-visual-source.js",
  "monitor-thumbnail-layer-policy.js",
  "monitor-thumbnail-background-layer.js",
  "monitor-thumbnail-window-layer.js",
  "monitor-desktop-thumbnail-v2.js"
].map(name=>fs.readFileSync(path.join(__dirname,"../extension",name),"utf8"));
class Element {
  constructor(tag,doc){
    this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.dataset={};this.children=[];this.attrs=new Map();this.isConnected=true;this.textContent="";
    this.style={backgroundImage:"",backgroundColor:"",setProperty(name,v){this[name]=v}};
    const classes=new Set();
    this.classList={add:n=>classes.add(n),remove:n=>classes.delete(n),contains:n=>classes.has(n)};
    Object.defineProperty(this,"className",{get(){return [...classes].join(" ")},set(s){classes.clear();for(const x of s.split(/\s+/).filter(Boolean))classes.add(x)}});
  }
  append(x){this.children.push(x);x.parentElement=this;}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(x=>x!==this);this.isConnected=false;}
  querySelectorAll(selector){const classes=selector.split(",").map(x=>x.trim().replace(/^\./,""));return this.children.filter(x=>classes.some(c=>x.classList.contains(c)))}
  setAttribute(k,v){this.attrs.set(k,String(v));}
  getAttribute(k){return this.attrs.get(k)??null;}
  removeAttribute(k){this.attrs.delete(k);}
}
const doc={createElement(tag){return new Element(tag,doc)}};
const D1="8ac6b16f-820b-4773-89e7-276ae4b84040",D2="c991b275-7933-4697-9d6e-73bf31ae4379";
function tile(id){const t=doc.createElement("span");t.className="monitor-desktop-thumb-visual";t.dataset.desktopId=id;return t;}
const visual1=tile(D1),visual2=tile(D2);
let currentRequest=async()=>({ok:false,error:"NO_TEST_REPLY"});
let currentFrame=async()=>null;
let controllerDecorations=0;
const ctx={WeakMap,Map,Set,Object,Array,Number,String,Date,Promise,TypeError,globalThis:null};
ctx.globalThis=ctx;vm.createContext(ctx);for(const code of modules)vm.runInContext(code,ctx);
const r=ctx.MonitorDesktopThumbnailV2;
r.configure({
  visualSource:ctx.MonitorDesktopVisualSource.create({request:message=>currentRequest(message)}),
  readFrame:desktopId=>currentFrame(desktopId),
  afterWindowRender(){controllerDecorations++}
});
assert.equal(typeof r.refreshWallpaper,"function");
const img="data:image/jpeg;base64,VALID_BYTES";
const source=id=>({ok:true,desktopId:id,wallpaper:{dataUri:img,baseColor:"#107c10",baseProof:"windows-base-color"}});
(async()=>{
  assert.equal(r.wallpaper(visual1,D1,source(D2)),false,"wrong GUID must fail closed");
  assert.equal(visual1.style.backgroundImage,"");
  assert.equal(r.wallpaper(visual1,D1,source(D1)),true);
  assert.equal(visual1.dataset.wallpaperSource,"native-guid-file");
  assert.equal(r.wallpaper(visual2,D2,source(D2)),true);
  const solid = {ok:true,desktopId:D1,wallpaper:{mode:"solid",color:"#10893e",proof:"windows-solid-mode"}};
  assert.equal(r.wallpaper(visual1,D1,solid),true);
  assert.equal(visual1.style.backgroundImage,"");
  assert.equal(visual1.style.backgroundColor,"#10893E");
  assert.equal(visual1.dataset.wallpaperSource,"native-solid-color");
  assert.equal(r.wallpaper(visual1,D1,{...solid,desktopId:D2}),false);
  assert.equal(visual1.style.backgroundColor,"#10893E","a rejected reply must not erase the last accepted background");
  assert.equal(visual1.dataset.wallpaperCapture,"retained");
  assert.equal(r.wallpaper(visual1,D1,source(D1)),true);
  assert.equal(visual1.style.backgroundColor,"#107C10");
  const tick=()=>new Promise(resolve=>setImmediate(resolve));
  let reads=0,releaseNormal;
  currentRequest=message=>{reads++;return new Promise(resolve=>{releaseNormal=()=>resolve(source(message.desktopId))})};
  const firstNormal=r.refreshWallpaper(visual1,D1,{force:true});
  const duplicateNormal=r.refreshWallpaper(visual1,D1);
  await tick();
  assert.equal(reads,1,"concurrent normal refreshes must share one Native read");
  releaseNormal();
  assert.deepEqual(await Promise.all([firstNormal,duplicateNormal]),[true,true]);

  // A full refresh can arrive after a background-only pass has already read
  // its queue but before the active promise clears.  That late upgrade must
  // start a follow-up window pass instead of resolving as background-only.
  currentRequest=async message=>source(message.desktopId);
  currentFrame=async()=>({
    meta:{desktopId:D1,previewVirtualLeft:0,previewVirtualTop:0,previewVirtualWidth:100,previewVirtualHeight:100,observedWindowHwnds:[]},
    frames:[]
  });
  const backgroundOnlyRace=r.refresh(visual1,D1,{includeWindows:false});
  let lateFullRace=null;
  const decorationsBeforeLateRace=controllerDecorations;
  await Promise.resolve().then(()=>Promise.resolve().then(()=>Promise.resolve().then(()=>{
    lateFullRace=r.refresh(visual1,D1,{includeWindows:true});
  })));
  await backgroundOnlyRace;
  const lateFullResult=await lateFullRace;
  assert.equal(lateFullResult.frameReady,true,"late window upgrade must not be lost at active-promise cleanup");
  assert.equal(controllerDecorations,decorationsBeforeLateRace+1,"late window upgrade must execute exactly one window pass");

  reads=0;
  const releases=[];
  currentRequest=message=>{reads++;return new Promise(resolve=>releases.push(value=>resolve({
    ok:true,desktopId:message.desktopId,wallpaper:{dataUri:value,baseColor:"#107c10",baseProof:"windows-base-color"}
  })))};
  const firstEvent=r.refreshWallpaper(visual1,D1,{force:true});
  await tick();
  const secondEvent=r.refreshWallpaper(visual1,D1,{force:true});
  assert.equal(reads,1,"a wallpaper event during a read queues instead of invalidating it");
  releases.shift()("data:image/jpeg;base64,OLD");
  await tick();
  assert.equal(reads,2,"multiple overlapping events coalesce to one follow-up read");
  releases.shift()(img);
  assert.deepEqual(await Promise.all([firstEvent,secondEvent]),[true,true]);
  assert(!visual1.style.backgroundImage.includes("OLD"));
  assert.equal(visual2.dataset.wallpaperCapture,"captured");
  const falsePhoto={ok:true,desktopId:D1,wallpaper:{dataUri:"data:image/svg+xml;base64,FAKE"}};
  assert.equal(r.wallpaper(visual1,D1,falsePhoto),false);
  assert.match(visual1.style.backgroundImage,/VALID_BYTES/,"invalid photo data must retain the last accepted background");
  assert.equal(r.wallpaper(visual1,D1,source(D1)),true);
  let decorations=0;
  const frame={meta:{desktopId:D1,previewVirtualLeft:0,previewVirtualTop:0,previewVirtualWidth:100,previewVirtualHeight:100,observedWindowHwnds:["123","124"]},
    frames:[
      {item:{hwnd:"123",left:10,top:15,width:40,height:30,z:0,cloaked:0,title:"Chrome"},captureState:"captured",physicalSource:"wgc-oneshot",dataUri:img,capturedAt:Date.now()},
      {item:{hwnd:"124",left:50,top:55,width:50,height:45,z:1,cloaked:2,title:"CLOAKED"},captureState:"placeholder",physicalSource:"windows-native",dataUri:"data:image/svg+xml;base64,FAKE",capturedAt:0}
    ]};
  currentFrame=async()=>frame;
  currentRequest=async message=>source(message.desktopId);
  const complete=await r.refresh(visual1,D1,{forceWallpaper:true});
  assert.equal(complete.ok,true);
  assert.equal(complete.wallpaperReady,true);
  assert.equal(complete.frameReady,true);
  assert.equal(complete.compositeReady,true);
  assert.equal(controllerDecorations,decorationsBeforeLateRace+2);
  currentRequest=async message=>({ok:false,desktopId:message.desktopId,error:"NO_WALLPAPER"});
  const backgroundFailed=await r.refresh(visual1,D1,{forceWallpaper:true});
  assert.equal(backgroundFailed.wallpaperReady,false);
  assert.equal(backgroundFailed.frameReady,true);
  assert.equal(backgroundFailed.ok,false,"a valid window frame must not hide a wallpaper failure");
  assert.equal(backgroundFailed.compositeReady,false);
  assert.match(visual1.style.backgroundImage,/VALID_BYTES/,"transient Native failure must retain last-good pixels");
  currentRequest=async message=>source(message.desktopId);
  assert.equal((await r.refresh(visual1,D1,{forceWallpaper:true})).ok,true);
  currentFrame=async()=>null;
  const frameUnavailable=await r.refresh(visual1,D1,{forceWallpaper:true});
  assert.equal(frameUnavailable.ok,true,"a valid background remains accepted when HWND capture is unavailable");
  assert.equal(frameUnavailable.wallpaperReady,true);
  assert.equal(frameUnavailable.frameReady,false);
  assert.equal(frameUnavailable.compositeReady,false);
  assert.equal(frameUnavailable.reason,"");
  assert.equal(frameUnavailable.frameReason,"FRAME_UNAVAILABLE");
  assert.equal(visual1.dataset.monitorThumbnailReady,"1");
  assert.equal(visual1.dataset.monitorThumbnailCompositeReady,"partial");
  assert.match(visual1.style.backgroundImage,/VALID_BYTES/);
  currentFrame=async()=>frame;
  assert.equal(r.windowFrame(visual1,D1,frame,{afterRender(){decorations++}}),true);
  assert.equal(decorations,1);
  const images=visual1.querySelectorAll(".monitor-desktop-thumb-window");
  assert.equal(images.length,2);
  const first=images.find(x=>x.dataset.hwnd==="123");
  const failed=images.find(x=>x.dataset.hwnd==="124");
  assert.equal(first.getAttribute("src"),img);
  assert.equal(first.dataset.captureState,"captured");
  assert.equal(failed.getAttribute("src"),null);
  assert.equal(failed.dataset.captureFailureReason,"NO_REAL_CAPTURE");
  assert(failed.classList.contains("monitor-thumb-v2-failed"));
  assert.equal(failed.style.display,"none","failed capture must leave the background visible without a simulated window");
  assert.equal(first.style.left,"10%");assert.equal(first.style.top,"15%");
  assert.equal(first.style.width,"40%");assert.equal(first.style.height,"30%");
  assert.equal(r.windowEvent(visual1,D1,{hwnd:"123",left:20,top:25,width:30,height:35,previewVirtualLeft:0,previewVirtualTop:0,previewVirtualWidth:100,previewVirtualHeight:100,visible:true}),true);
  assert.equal(first.style.left,"20%");assert.equal(first.style.top,"25%");
  assert.equal(first.style.width,"30%");assert.equal(first.style.height,"35%");
  assert.equal(r.windowEvent(visual2,D2,{hwnd:"123",left:0,top:0,width:10,height:10,previewVirtualWidth:100,previewVirtualHeight:100}),false,"an event cannot move a HWND owned by another desktop tile");
  assert.equal(first.style["z-index"],"10000");assert.equal(failed.style["z-index"],"9999");
  assert.equal(visual1.querySelectorAll(".monitor-thumb-v2-status").find(x=>x.dataset.hwnd==="124").hidden,true);
  assert.equal(r.windowFrame(visual2,D2,frame),false,"cross-desktop Windows frame must be rejected");
  const removed={...frame,meta:{...frame.meta,observedWindowHwnds:["123"]},frames:[frame.frames[0]]};
  assert.equal(r.windowFrame(visual1,D1,removed),true);
  assert.equal(visual1.querySelectorAll(".monitor-desktop-thumb-window").length,1);
  const cloakedReused={...removed,frames:[{...frame.frames[0],item:{...frame.frames[0].item,cloaked:2},capturedAt:Date.now()}]};
  r.windowFrame(visual1,D1,cloakedReused);
  assert.equal(first.getAttribute("src"),img,"a Shell-cloaked HWND may display its verified real WGC pixels");
  assert.equal(first.dataset.captureState,"captured");
  assert.equal(first.dataset.captureFailureReason,"");
  assert.equal(first.style.display,"block");
  const frozen={...removed,frames:[{...frame.frames[0],physicalSource:"monitor-frozen",dataUri:img}]};
  r.windowFrame(visual1,D1,frozen);
  assert.equal(first.getAttribute("src"),null,"previous monitor popup screenshots forbidden");
  assert.equal(first.dataset.captureFailureReason,"SAVED_FRAME_REJECTED");
  assert.equal(r.wallpaper(visual1,D1,source(D1)),true);
  // Existing DOM from legacy renderer is discarded on first attachment.
  const legacy=tile(D1);const obsolete=doc.createElement("img");obsolete.className="monitor-desktop-thumb-window";obsolete.dataset.hwnd="987";legacy.append(obsolete);
  r.resolve(legacy,D1);
  assert.equal(legacy.querySelectorAll(".monitor-desktop-thumb-window").length,0);
  assert.equal(visual2.dataset.wallpaperDesktopId,D2.toLowerCase());
  let nativeReads=0;
  currentRequest=async message=>{nativeReads++;return source(message.desktopId)};
  await r.refreshWallpaper(visual1,D1);
  assert.equal(nativeReads,0,"normal thumbnail repaint must not poll wallpapers");
  await r.refreshWallpaper(visual1,D1,{force:true});
  assert.equal(nativeReads,1,"a native wallpaper-change signal forces exactly one GUID read");
  const back={...removed,frames:[{...frame.frames[0],capturedAt:Date.now()}]};
  r.windowFrame(visual1,D1,back);
  assert.equal(first.getAttribute("src"),img,"a fresh physical capture restores pixels after a rejected saved frame");
  const timed={...removed,frames:[{...frame.frames[0],capturedAt:Date.now()-30000}]};
  r.windowFrame(visual1,D1,timed);
  assert.equal(first.getAttribute("src"),img,"a stale read must not erase the last accepted HWND pixels");
  assert.equal(first.dataset.captureState,"retained");
  assert.equal(first.dataset.captureFailureReason,"STALE_CAPTURE");
  r.windowFrame(visual1,D1,back);
  assert.equal(first.getAttribute("src"),img);
  assert.equal(r.frameFailure(visual1,D1,"FRAME_UNAVAILABLE"),true);
  assert.equal(first.getAttribute("src"),img,"a transient Native failure retains fresh accepted pixels");
  assert.equal(first.dataset.captureState,"retained");
  assert.equal(first.dataset.captureFailureReason,"FRAME_UNAVAILABLE");
  first.dataset.monitorCapturedAt=String(Date.now()-30000);
  assert.equal(r.frameFailure(visual1,D1,"FRAME_UNAVAILABLE"),true);
  assert.equal(first.getAttribute("src"),img,"an uncertain frame failure must retain accepted pixels regardless of age");
  assert.equal(first.dataset.captureState,"retained");
  assert.equal(r.windowFrame(visual1,D2,back),false,"wrong GUID frame rejected");
  // The most recent V2 window snapshot owns pixels; stale results and
  // lifecycle removal must not bring back previous HWND captures.
  const olderToken=r.beginFrame(visual1,D1);
  const latestToken=r.beginFrame(visual1,D1);
  assert.equal(r.windowFrame(visual1,D1,back,{frameToken:olderToken}),false);
  assert.equal(r.windowFrame(visual1,D1,back,{frameToken:latestToken}),true);
  assert.equal(r.removeWindow(visual1,D2,"123"),false);
  assert.equal(r.removeWindow(visual1,D1,"123"),true);
  assert.equal(visual1.querySelectorAll(".monitor-desktop-thumb-window").length,0);
  assert.equal(r.windowFrame(visual1,D1,back,{frameToken:latestToken}),false);
  assert.equal(r.frameFailure(visual1,D1,"OLD_FAILURE",latestToken),false);
  console.log("PASS: V2 uses exact GUID wallpapers, strict HWND frame provenance, transparent failures, Z/geometry and node decoration callback, stale async rejection, no legacy fallback.");
})().catch(err=>{console.error(err);process.exitCode=1});
