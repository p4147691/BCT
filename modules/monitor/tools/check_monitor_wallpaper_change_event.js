"use strict";
const fs=require("node:fs"),assert=require("node:assert/strict"),vm=require("node:vm");
const js=fs.readFileSync("modules/monitor/extension/monitor.js","utf8");
const native=fs.readFileSync("modules/monitor/native/src/MonitorDesktopHost.cs","utf8");
const watcher=fs.readFileSync("modules/monitor/native/src/MonitorWallpaperRegistryWatcher.cs","utf8");
assert.match(native,/StartWallpaperChangeEvents\(\);/);
assert.match(native,/MonitorWallpaperRegistryWatcher\.Start\(/);
assert.match(watcher,/RegNotifyChangeKeyValue\(/);
assert.match(native,/"type", "desktopWallpaperChanged"/);
const start=js.indexOf('    if (response?.event === true && response?.type === "desktopWallpaperChanged")');
const end=js.indexOf('    if (response?.event === true && response?.type === "monitorDragPreviewReleased")',start);
assert(start>0 && end>start);
const branch=js.slice(start,end);
const first="8ac6b16f-820b-4773-89e7-276ae4b84040";
const second="c991b275-7933-4697-9d6e-73bf31ae4379";
const visuals=[first,second].map(desktopId=>({dataset:{desktopId},style:{backgroundImage:"old"}}));
const seen=[];
const thumbs={dataset:{},querySelectorAll:()=>visuals};
const adapter={refreshWallpaper:(visual,id,read)=>{seen.push(id);return read(id).then(data=>data.ok===true)}};
const env={
 response:{event:true,type:"desktopWallpaperChanged"},
 monitorDesktopThumbs:thumbs,
 globalThis:{MonitorDesktopThumbnailV2:adapter},
 MONITOR_WALLPAPER_MAX_WIDTH:960,MONITOR_WALLPAPER_MAX_HEIGHT:600,
 monitorNativeVisualRead:async req=>({ok:true,desktopId:req.desktopId}),
 Date,Promise,String
};
vm.createContext(env);
vm.runInContext("(function(){"+branch+"})()",env);
assert.deepEqual(seen,[first,second],"event without a GUID refreshes independently by visual GUID");
assert.equal(typeof thumbs.dataset.wallpaperEventAt,"string");
seen.length=0;
env.response={event:true,type:"desktopWallpaperChanged",desktopId:second};
vm.runInContext("(function(){"+branch+"})()",env);
assert.deepEqual(seen,[second],"explicit event GUID never corrupts another desktop");
assert.doesNotMatch(branch,/monitorWallpaperActuals|monitorWallpaperCache|monitorPreviewWallpaper/);
assert.match(branch,/MonitorDesktopThumbnailV2\.refreshWallpaper/);
assert.match(branch,/getDesktopVisualSnapshot/);
console.log("PASS: Windows wallpaper event refreshes only matching v2 GUID tiles using Native file pixels, never legacy cache");
