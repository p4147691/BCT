"use strict";
// Read-only contract between the configured Native wallpaper source and the
// isolated V2 browser renderer. No screenshot/user pixels are saved.
const fs=require("node:fs"),path=require("node:path"),assert=require("node:assert/strict");
const {spawnSync}=require("node:child_process");
const {chromium}=require("D:/TOOLS/BrowserAutomationSDK/node_modules/playwright");
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,"..","native","com.pas40.desktop_window_monitor_control.json"),"utf8"));
const native=manifest.path;

function request(message){
 const requestId="physical-"+Math.random().toString(36).slice(2);
 const data=Buffer.from(JSON.stringify({...message,requestId}),"utf8");
 const frame=Buffer.alloc(4+data.length);frame.writeUInt32LE(data.length,0);data.copy(frame,4);
 const p=spawnSync(native,[],{input:frame,maxBuffer:4*1024*1024,timeout:16000,windowsHide:true});
 if(p.error)throw p.error;
 assert.equal(p.status,0,"read-only native host process failed");
 let offset=0,reply=null;
 while(offset+4<=p.stdout.length){
  const size=p.stdout.readUInt32LE(offset);offset+=4;
  assert(size>0&&size<=4*1024*1024&&p.stdout.length>=offset+size);
  const row=JSON.parse(p.stdout.subarray(offset,offset+size).toString("utf8"));offset+=size;
  if(row.requestId===requestId)reply=row;
 }
 assert(reply,"correlated Native response missing");
 return reply;
}

(async()=>{
 const desktops=request({type:"getVirtualDesktops"});
 assert.equal(desktops.ok,true,desktops.error||"getVirtualDesktops failed");
 const ids=(desktops.desktopIds||[]).map(x=>String(x).toLowerCase()).slice(0,2);
 assert.equal(ids.length,2,"physical D1/D2 acceptance requires two desktops");
 const frames=ids.map(desktopId=>{
  const reply=request({type:"getDesktopVisualSnapshot",desktopId,maxWidth:160,maxHeight:90,quality:55});
  assert.equal(reply.ok,true,reply.error||"getDesktopVisualSnapshot failed");
  assert.equal(String(reply.desktopId).toLowerCase(),desktopId);
  if(reply.wallpaper?.mode==="solid")assert.match(reply.wallpaper.color||"",/^#[0-9a-f]{6}$/i);
  else {
    assert.match(reply.wallpaper?.dataUri||"",/^data:image\/(?:jpeg|png|webp);base64,/);
    assert.match(reply.wallpaper?.baseColor||"",/^#[0-9a-f]{6}$/i);
  }
  return reply;
 });
 const browser=await chromium.launch({executablePath:"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",headless:true,args:["--no-first-run","--no-default-browser-check"]});
 try{
  const page=await browser.newPage({viewport:{width:530,height:200},deviceScaleFactor:1});
  await page.setContent("<!doctype html><meta charset='utf-8'><style>.monitor-desktop-thumb-visual{display:inline-block;width:240px;height:145px;position:relative;background-size:100% 100%;margin:6px;background-color:#333}</style>"+
  ids.map((id,i)=>'<div id="d'+(i+1)+'" class="monitor-desktop-thumb-visual" data-desktop-id="'+id+'"></div>').join(""));
  for(const name of ["monitor-thumbnail-contract.js","monitor-desktop-visual-source.js","monitor-thumbnail-background-layer.js","monitor-thumbnail-window-layer.js","monitor-desktop-thumbnail-v2.js"]){
   await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,"../extension",name),"utf8")});
  }
  const result=await page.evaluate(async({ids,frames})=>{
    const engine=window.MonitorDesktopThumbnailV2;
    const tiles=[document.getElementById("d1"),document.getElementById("d2")];
    engine.configure({visualSource:window.MonitorDesktopVisualSource.create({request:request=>{
      const index=ids.indexOf(String(request.desktopId||"").toLowerCase());
      return Promise.resolve(index>=0?frames[index]:{ok:false,error:"UNKNOWN_DESKTOP"});
    }})});
    await Promise.all(tiles.map((tile,i)=>engine.refreshWallpaper(tile,ids[i])));
    const normal=tiles.map(x=>({id:x.dataset.wallpaperDesktopId,state:x.dataset.wallpaperCapture,source:x.dataset.wallpaperSource,
      image:getComputedStyle(x).backgroundImage,color:getComputedStyle(x).backgroundColor}));
    const cssColor=value=>{const probe=document.createElement("i");probe.style.color=value;document.body.append(probe);const normalized=getComputedStyle(probe).color;probe.remove();return normalized;};
    const exact=(view,frame)=>frame.wallpaper.mode==="solid"
      ? view.state==="captured"&&view.source==="native-solid-color"&&view.color===cssColor(frame.wallpaper.color)
      : view.state==="captured"&&view.source==="native-guid-file"&&
        view.image.includes(frame.wallpaper.dataUri.slice(18,65))&&view.color===cssColor(frame.wallpaper.baseColor);
    const passes=normal.map((view,i)=>exact(view,frames[i]));
    const priorStyle={image:tiles[0].style.backgroundImage,color:tiles[0].style.backgroundColor};
    const wrong=engine.wallpaper(tiles[0],ids[0],frames[1]);
    return {ids:normal.map(x=>x.id),passes,kinds:normal.map(x=>x.source),wrongIdAccepted:wrong,
      crossIdRetained:tiles[0].style.backgroundImage===priorStyle.image&&tiles[0].style.backgroundColor===priorStyle.color};
  },{ids,frames});
  if(!result.passes.every(Boolean))console.error("NATIVE_TO_EDGE_V2_MISMATCH "+JSON.stringify({result,kinds:frames.map(frame=>frame.wallpaper?.mode||""),sizes:frames.map(frame=>String(frame.wallpaper?.dataUri||"").length)}));
  assert.deepEqual(result.ids,ids);assert.deepEqual(result.passes,[true,true]);
  assert.equal(result.wrongIdAccepted,false);assert.equal(result.crossIdRetained,true);
  console.log("PASS ACTUAL_NATIVE_TO_EDGE_V2: configured correlated Native D1/D2 "+result.kinds.join("+")+" rendered by exact GUID; mismatch rejected");
 }finally{await browser.close()}
})().catch(e=>{console.error(e.stack||e.message);process.exitCode=1});
