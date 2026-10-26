"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const code=fs.readFileSync(path.join(__dirname,"../extension/monitor-desktop-thumbnail-v2.js"),"utf8");
class Element {
  constructor(tag,doc){
    this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.dataset={};this.children=[];this.attrs=new Map();this.isConnected=true;this.textContent="";
    this.style={backgroundImage:"",setProperty(name,v){this[name]=v}};
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
const ctx={WeakMap,Map,Set,Object,Array,Number,String,Date,globalThis:null};
ctx.globalThis=ctx;vm.createContext(ctx);vm.runInContext(code,ctx);
const r=ctx.MonitorDesktopThumbnailV2;
assert.equal(typeof r.refreshWallpaper,"function");
const img="data:image/jpeg;base64,VALID_BYTES";
const source=id=>({ok:true,desktopId:id,wallpaper:{dataUri:img}});
(async()=>{
  assert.equal(r.wallpaper(visual1,D1,source(D2)),false,"wrong GUID must fail closed");
  assert.equal(visual1.style.backgroundImage,"");
  assert.equal(r.wallpaper(visual1,D1,source(D1)),true);
  assert.equal(visual1.dataset.wallpaperSource,"native-guid-file");
  assert.equal(r.wallpaper(visual2,D2,source(D2)),true);
  const solid = {ok:true,desktopId:D1,wallpaper:{mode:"solid",color:"#10893e",proof:"windows-solid-mode"}};
  assert.equal(r.wallpaper(visual1,D1,solid),true);
  assert.equal(visual1.style.backgroundImage,"");
  assert.equal(visual1.style.backgroundColor,"#10893e");
  assert.equal(visual1.dataset.wallpaperSource,"native-solid-color");
  assert.equal(r.wallpaper(visual1,D1,{...solid,desktopId:D2}),false);
  assert.equal(visual1.style.backgroundColor,"");
  assert.equal(r.wallpaper(visual1,D1,source(D1)),true);
  assert.equal(visual1.style.backgroundColor,"");
  let unblock;const old=new Promise(f=>unblock=f);
  const oldTurn=r.refreshWallpaper(visual1,D1,()=>old,{force:true});
  const latest=await r.refreshWallpaper(visual1,D1,async()=>source(D1),{force:true});
  unblock({ok:true,desktopId:D1,wallpaper:{dataUri:"data:image/jpeg;base64,OLD"}});
  assert.equal(await oldTurn,false,"old async image must be rejected");
  assert.equal(latest,true);assert(!visual1.style.backgroundImage.includes("OLD"));
  assert.equal(visual2.dataset.wallpaperCapture,"captured");
  const falsePhoto={ok:true,desktopId:D1,wallpaper:{dataUri:"data:image/svg+xml;base64,FAKE"}};
  assert.equal(r.wallpaper(visual1,D1,falsePhoto),false);
  assert.equal(visual1.style.backgroundImage,"");
  assert.equal(r.wallpaper(visual1,D1,source(D1)),true);
  let decorations=0;
  const frame={meta:{desktopId:D1,previewVirtualLeft:0,previewVirtualTop:0,previewVirtualWidth:100,previewVirtualHeight:100,observedWindowHwnds:["123","124"]},
    frames:[
      {item:{hwnd:"123",left:10,top:15,width:40,height:30,z:0,cloaked:0,title:"Chrome"},captureState:"captured",physicalSource:"wgc-oneshot",dataUri:img,capturedAt:Date.now()},
      {item:{hwnd:"124",left:50,top:55,width:50,height:45,z:1,cloaked:2,title:"CLOAKED"},captureState:"placeholder",physicalSource:"windows-native",dataUri:"data:image/svg+xml;base64,FAKE",capturedAt:0}
    ]};
  assert.equal(r.windowFrame(visual1,D1,frame,{afterRender(){decorations++}}),true);
  assert.equal(decorations,1);
  const images=visual1.querySelectorAll(".monitor-desktop-thumb-window");
  assert.equal(images.length,2);
  const first=images.find(x=>x.dataset.hwnd==="123");
  const failed=images.find(x=>x.dataset.hwnd==="124");
  assert.equal(first.getAttribute("src"),img);
  assert.equal(first.dataset.captureState,"captured");
  assert.equal(failed.getAttribute("src"),null);
  assert.equal(failed.dataset.captureFailureReason,"CLOAKED");
  assert(failed.classList.contains("monitor-thumb-v2-failed"));
  assert.equal(first.style.left,"10%");assert.equal(first.style.top,"15%");
  assert.equal(first.style.width,"40%");assert.equal(first.style.height,"30%");
  assert.equal(first.style["z-index"],"10000");assert.equal(failed.style["z-index"],"9999");
  assert.match(visual1.querySelectorAll(".monitor-thumb-v2-status").find(x=>x.dataset.hwnd==="124").textContent,/CLOAKED/);
  assert.equal(r.windowFrame(visual2,D2,frame),false,"cross-desktop Windows frame must be rejected");
  const removed={...frame,meta:{...frame.meta,observedWindowHwnds:["123"]},frames:[frame.frames[0]]};
  assert.equal(r.windowFrame(visual1,D1,removed),true);
  assert.equal(visual1.querySelectorAll(".monitor-desktop-thumb-window").length,1);
  const cloakedReused={...removed,frames:[{...frame.frames[0],item:{...frame.frames[0].item,cloaked:2},capturedAt:Date.now()}]};
  r.windowFrame(visual1,D1,cloakedReused);
  assert.equal(first.getAttribute("src"),null,"CLOAKED window must not mask real wallpaper even with cached JPEG");
  assert.equal(first.dataset.captureFailureReason,"CLOAKED");
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
  await r.refreshWallpaper(visual1,D1,async id=>{nativeReads++;return source(id)});
  assert.equal(nativeReads,0,"normal thumbnail repaint must not poll wallpapers");
  await r.refreshWallpaper(visual1,D1,async id=>{nativeReads++;return source(id)},{force:true});
  assert.equal(nativeReads,1,"a native wallpaper-change signal forces exactly one GUID read");
  const timed={...removed,frames:[{...frame.frames[0],capturedAt:Date.now()-30000}]};
  r.windowFrame(visual1,D1,timed);
  assert.equal(first.getAttribute("src"),null,"old image must not claim a fresh capture");
  assert.equal(first.dataset.captureFailureReason,"STALE_CAPTURE");
  const back={...removed,frames:[{...frame.frames[0],capturedAt:Date.now()}]};
  r.windowFrame(visual1,D1,back);
  assert.equal(first.getAttribute("src"),img);
  assert.equal(r.frameFailure(visual1,D1,"FRAME_UNAVAILABLE"),true);
  assert.equal(first.getAttribute("src"),null,"Native failure clears any old pixels");
  assert.equal(first.dataset.captureFailureReason,"FRAME_UNAVAILABLE");
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
