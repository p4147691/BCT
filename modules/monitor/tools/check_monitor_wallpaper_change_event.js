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
const adapter={refreshBackground:(visual,id,options)=>{seen.push({id,options});return Promise.resolve({ok:true,wallpaperReady:true,frameReady:null})}};
const env={
 response:{event:true,type:"desktopWallpaperChanged"},
 monitorDesktopThumbs:thumbs,
 globalThis:{MonitorDesktopThumbnailV2:adapter},
 Date,Promise,String
};
vm.createContext(env);
vm.runInContext("(function(){"+branch+"})()",env);
assert.deepEqual(seen.map(x=>x.id),[first,second],"event without a GUID refreshes independently by visual GUID");
assert(seen.every(x=>x.options?.forceWallpaper===true),"Windows change events must force a fresh canonical read");
assert.equal(typeof thumbs.dataset.wallpaperEventAt,"string");
seen.length=0;
env.response={event:true,type:"desktopWallpaperChanged",desktopId:second};
vm.runInContext("(function(){"+branch+"})()",env);
assert.deepEqual(seen.map(x=>x.id),[second],"explicit event GUID never corrupts another desktop");
assert.doesNotMatch(branch,/monitorWallpaperActuals|monitorWallpaperCache|monitorPreviewWallpaper/);
assert.match(branch,/MonitorDesktopThumbnailV2\.refreshBackground/);
assert.match(branch,/\{forceWallpaper:true\}/);
assert.doesNotMatch(branch,/getDesktopVisualSnapshot|monitorNativeVisualRead|monitorNative\(/,
  "event handling delegates input selection to the injected thumbnail source");
console.log("PASS: Windows wallpaper event forces only matching V2 GUID tiles through the configured visual source");
