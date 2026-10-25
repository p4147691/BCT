"use strict";
const fs=require("fs"),vm=require("vm"),assert=require("assert/strict");
const source=fs.readFileSync("modules/monitor/extension/monitor.js","utf8");
const start=source.indexOf("async function getObservedWallpaper(");
const end=source.indexOf("async function applyObservedWallpaper(",start);
assert(start>0&&end>start);
const fakeId="desktop-test";
let nativeCalls=0;
const actual=new Map([[fakeId,{dataUri:"data:image/png;base64,OLD",at:1}]]);
const context={
 MONITOR_PIXEL_VISUALS_ENABLED:true,monitorWallpaperActuals:actual,monitorWallpaperCache:new Map(),monitorWallpaperFallbacks:new Map(),
 MONITOR_WALLPAPER_CACHE_MS:15000,MONITOR_WALLPAPER_CACHE_LIMIT:3,MONITOR_WALLPAPER_MAX_WIDTH:960,MONITOR_WALLPAPER_MAX_HEIGHT:600,
 monitorCoreNative:async()=>{nativeCalls++;return {wallpaper:{dataUri:"data:image/png;base64,NEW"}}},
 monitorLightweightWallpaperDataUri:async x=>x,monitorRememberWallpaperEntry:(map,key,data)=>map.set(key,{dataUri:data,at:Date.now()}),
 monitorNative:async()=>({ready:true}),Date,String
};
vm.createContext(context);
vm.runInContext(source.slice(start,end)+"\nthis.readWallpaper=getObservedWallpaper;",context);
(async()=>{
 const old=await context.readWallpaper(fakeId,false);
 assert.equal(old,"data:image/png;base64,OLD");
 assert.equal(nativeCalls,0);
 const updated=await context.readWallpaper(fakeId,true);
 assert.equal(updated,"data:image/png;base64,NEW");
 assert.equal(nativeCalls,1);
 console.log("PASS: forced wallpaper refresh bypasses retained prior image and fetches Native pixels");
})().catch(e=>{console.error(e);process.exitCode=1});