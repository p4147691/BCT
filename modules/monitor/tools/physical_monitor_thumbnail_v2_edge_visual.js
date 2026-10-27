"use strict";
// Visual smoke test of the isolated V2 renderer in its own headless Edge profile.
// Does not attach to or control the user's operating Chrome, RCC, or Monitor.
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path");
const {chromium}=require("D:/TOOLS/BrowserAutomationSDK/node_modules/playwright");
const D1="8ac6b16f-820b-4773-89e7-276ae4b84040";
const D2="c991b275-7933-4697-9d6e-73bf31ae4379";
(async()=>{
 const browser=await chromium.launch({
   executablePath:"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
   headless:true,args:["--no-first-run","--no-default-browser-check"]
 });
 try{
  const page=await browser.newPage({viewport:{width:650,height:280},deviceScaleFactor:1});
  await page.setContent('<!doctype html><html><head><style>'+
   '.monitor-desktop-thumb-visual{display:inline-block;width:240px;height:145px;position:relative;overflow:hidden;background-size:100% 100%;background-color:#555;margin:8px}'+
   '.monitor-desktop-thumb-window{position:absolute;display:block;object-fit:fill}'+
   '.monitor-desktop-thumb-window.monitor-thumb-v2-failed{border:1px dashed #ffbe64;background:transparent!important;box-shadow:none;color:transparent}'+
   '.monitor-thumb-v2-status{position:absolute;background:#151515dd;color:#ffe0af;font:10px sans-serif;max-width:85%}'+
   '.monitor-thumb-v2-status[hidden]{display:none!important}'+
   '</style></head><body>'+
   '<span id="d1" class="monitor-desktop-thumb-visual" data-desktop-id="'+D1+'"></span>'+
   '<span id="d2" class="monitor-desktop-thumb-visual" data-desktop-id="'+D2+'"></span>'+
   '</body></html>');
  for(const name of ["monitor-thumbnail-contract.js","monitor-desktop-visual-source.js","monitor-thumbnail-layer-policy.js","monitor-thumbnail-background-layer.js","monitor-thumbnail-window-layer.js","monitor-desktop-thumbnail-v2.js"]){
   await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,"../extension",name),"utf8")});
  }
  const result=await page.evaluate(async({D1,D2})=>{
    const engine=window.MonitorDesktopThumbnailV2;
    const tiles=[document.getElementById("d1"),document.getElementById("d2")];
    const photo=(color)=>{
      const c=document.createElement("canvas");c.width=50;c.height=50;
      const g=c.getContext("2d");g.fillStyle=color;g.fillRect(0,0,50,50);
      return c.toDataURL("image/png");
    };
    const b=photo("#3b5fe8");
    const native=async request=>({ok:true,desktopId:request.desktopId,wallpaper:request.desktopId===D1
      ?{mode:"solid",color:"#10893E",proof:"windows-solid-mode"}:{dataUri:b,baseColor:"#2D7D9A",baseProof:"windows-base-color"}});
    engine.configure({
      visualSource:window.MonitorDesktopVisualSource.create({request:native}),
      layerPolicy:window.MonitorThumbnailLayerPolicy.create(window.MonitorThumbnailLayerPolicy.MODES.BACKGROUND_WINDOWS)
    });
    await Promise.all(tiles.map((t,i)=>engine.refreshWallpaper(t,i===0?D1:D2)));
    const before=tiles.map(t=>({image:getComputedStyle(t).backgroundImage,color:getComputedStyle(t).backgroundColor,source:t.dataset.wallpaperSource}));
    const failedImage=photo("#111111");
    const nativeFrame={meta:{desktopId:D1,previewVirtualLeft:0,previewVirtualTop:0,previewVirtualWidth:100,previewVirtualHeight:100,observedWindowHwnds:["801","802"]},
      frames:[
        {item:{hwnd:"801",left:25,top:10,width:50,height:70,z:1,cloaked:0,title:"Actual window"},
          physicalSource:"wgc-oneshot",captureState:"captured",capturedAt:Date.now(),dataUri:failedImage},
        {item:{hwnd:"802",left:5,top:5,width:20,height:20,z:2,cloaked:2,title:"Old Other Desktop"},
          physicalSource:"wgc-oneshot",captureState:"captured",capturedAt:Date.now(),dataUri:failedImage}
      ]};
    engine.windowFrame(tiles[0],D1,nativeFrame);
    const img=tiles[0].querySelector('.monitor-desktop-thumb-window[data-hwnd="801"]');
    const failed=tiles[0].querySelector('.monitor-desktop-thumb-window[data-hwnd="802"]');
    const fail=tiles[0].querySelector('.monitor-thumb-v2-status[data-hwnd="802"]');
    const rect=img.getBoundingClientRect(),tileRect=tiles[0].getBoundingClientRect();
    const result={
      solidBackground:before[0].image==="none"&&before[0].color==="rgb(16, 137, 62)"&&before[0].source==="native-solid-color",
      photoBackground:before[1].image.includes("data:image/png;base64")&&before[1].source==="native-guid-file",
      d1Guid:tiles[0].dataset.wallpaperDesktopId,d2Guid:tiles[1].dataset.wallpaperDesktopId,
      failedHasSrc:failed.hasAttribute("src"),failedState:failed.dataset.captureFailureReason,
      errorVisible:getComputedStyle(fail).display!=="none" && fail.textContent.includes("CLOAKED"),
      windowLeftFraction:(rect.left-tileRect.left)/tileRect.width,
      windowTopFraction:(rect.top-tileRect.top)/tileRect.height,
      d2Windows:tiles[1].querySelectorAll(".monitor-desktop-thumb-window").length
    };
    engine.frameFailure(tiles[0],D1,"FRAME_UNAVAILABLE");
    result.failureAfterMissingFrame=img.dataset.captureFailureReason;
    return result;
  },{D1,D2});
  assert.equal(result.solidBackground,true,"D1 must render the confirmed Windows color, not the CSS gray default");
  assert.equal(result.photoBackground,true,"D2 must preserve the confirmed photo path");
  assert.equal(result.d1Guid,D1);assert.equal(result.d2Guid,D2);
  assert.equal(result.failedHasSrc,false,"CLOAKED cannot cover real background");
  assert.equal(result.failedState,"CLOAKED");
  assert.equal(result.errorVisible,false,"failed capture diagnostics must not become a third visual layer");
  assert(Math.abs(result.windowLeftFraction-0.25)<0.03);
  assert(Math.abs(result.windowTopFraction-0.10)<0.03);
  assert.equal(result.d2Windows,0);
  assert.equal(result.failureAfterMissingFrame,"FRAME_UNAVAILABLE");
  console.log("PASS ISOLATED_EDGE_VISUAL: exact GUID solid/photo backgrounds, real-window-only HWND layer, transparent failures, geometry, separate desktop, missing-frame handling");
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
