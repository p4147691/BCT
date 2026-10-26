"use strict";
// Read-only contract between the installed Native wallpaper GUID file source
// and the isolated V2 browser renderer. No screenshot/user pixels are saved.
const fs=require("node:fs"),path=require("node:path"),assert=require("node:assert/strict");
const {spawnSync}=require("node:child_process");
const {chromium}=require("D:/TOOLS/BrowserAutomationSDK/node_modules/playwright");
const native="D:/ChromeExtensions/DesktopWindow-Monitor/native/1.9.20.177-registry-watch/DesktopWindowMonitorControlHost.exe";
const ids=["8ac6b16f-820b-4773-89e7-276ae4b84040","c991b275-7933-4697-9d6e-73bf31ae4379"];
function request(desktopId){
 const data=Buffer.from(JSON.stringify({type:"getDesktopVisualSnapshot",desktopId,maxWidth:160,maxHeight:90,quality:55}),"utf8");
 const frame=Buffer.alloc(4+data.length);frame.writeUInt32LE(data.length,0);data.copy(frame,4);
 const p=spawnSync(native,[],{input:frame,maxBuffer:1024*1024,timeout:16000,windowsHide:true});
 if(p.error)throw p.error;
 assert.equal(p.status,0,"read-only native host process failed");
 assert(p.stdout.length>4);
 const size=p.stdout.readUInt32LE(0);
 assert(size>0&&size<=1024*1024&&p.stdout.length>=size+4);
 const reply=JSON.parse(p.stdout.subarray(4,4+size).toString("utf8"));
 assert.equal(reply.ok,true);
 assert.equal(reply.desktopId.toLowerCase(),desktopId);
 assert.match(reply.wallpaper?.dataUri||"",/^data:image\/(?:jpeg|png|webp);base64,/);
 return reply;
}
(async()=>{
 const frames=ids.map(request);
 const browser=await chromium.launch({executablePath:"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",headless:true,args:["--no-first-run","--no-default-browser-check"]});
 try{
  const page=await browser.newPage({viewport:{width:530,height:200},deviceScaleFactor:1});
  await page.setContent("<!doctype html><meta charset='utf-8'><style>.monitor-desktop-thumb-visual{display:inline-block;width:240px;height:145px;position:relative;background-size:100% 100%;margin:6px;background-color:#333}</style>"+
  ids.map((id,i)=>'<div id="d'+(i+1)+'" class="monitor-desktop-thumb-visual" data-desktop-id="'+id+'"></div>').join(""));
  await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,"../extension/monitor-desktop-thumbnail-v2.js"),"utf8")});
  const result=await page.evaluate(async({ids,frames})=>{
    const engine=window.MonitorDesktopThumbnailV2;
    const tiles=[document.getElementById("d1"),document.getElementById("d2")];
    await Promise.all(tiles.map((tile,i)=>engine.refreshWallpaper(tile,ids[i],async()=>frames[i])));
    const normal=tiles.map(x=>({id:x.dataset.wallpaperDesktopId,state:x.dataset.wallpaperCapture,source:x.dataset.wallpaperSource,
      image:getComputedStyle(x).backgroundImage}));
    const wrong=engine.wallpaper(tiles[0],ids[0],frames[1]);
    return {
      d1:normal[0].id,d2:normal[1].id,
      d1Pass:normal[0].state==="captured" && normal[0].source==="native-guid-file" &&
             normal[0].image.includes(frames[0].wallpaper.dataUri.slice(18,65)),
      d2Pass:normal[1].state==="captured" && normal[1].source==="native-guid-file" &&
             normal[1].image.includes(frames[1].wallpaper.dataUri.slice(18,65)),
      differentPixels:frames[0].wallpaper.dataUri!==frames[1].wallpaper.dataUri,
      wrongIdAccepted:wrong,
      crossIdCleared:tiles[0].style.backgroundImage===""
    };
  },{ids,frames});
  assert.equal(result.d1,ids[0]);assert.equal(result.d2,ids[1]);
  assert.equal(result.d1Pass,true);assert.equal(result.d2Pass,true);
  assert.equal(result.differentPixels,true);
  assert.equal(result.wrongIdAccepted,false);
  assert.equal(result.crossIdCleared,true);
  console.log("PASS ACTUAL_NATIVE_TO_EDGE_V2: distinct D1/D2 registry-file pixels displayed by exact GUID, mismatched GUID rejected, no persisted user pixels");
 }finally{await browser.close()}
})().catch(e=>{console.error(e.message);process.exitCode=1});
