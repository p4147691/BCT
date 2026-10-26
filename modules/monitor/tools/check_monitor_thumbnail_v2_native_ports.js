"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const source=fs.readFileSync("modules/monitor/extension/monitor.js","utf8");
const anchor="port.onMessage.addListener((response) => {";
const handlers=[];
let pos=0;
while(true){
 const a=source.indexOf(anchor,pos);
 if(a<0)break;
 const nextDisconnect=source.indexOf("port.onDisconnect.addListener",a+anchor.length);
 if(nextDisconnect<0)throw Error("NATIVE_ONDISCONNECT_NOT_FOUND");
 const b=source.lastIndexOf("});",nextDisconnect);
 if(b<a)throw Error("NATIVE_PORT_LISTENER_CLOSE_NOT_FOUND");
 handlers.push(source.slice(a+anchor.length,b));
 pos=nextDisconnect+25;
}
const relevant=handlers.filter(body=>body.includes("monitorNativePending.shift()") || body.includes("monitorCoreNativePending.shift()"));
assert.equal(relevant.length,2,"two long-lived control ports are deliberately separate");
const first=[];const second=[];const observations=[];
const visual={dataset:{desktopId:"8ac6b16f-820b-4773-89e7-276ae4b84040"}};
const globals={
 Promise,Date,String,window:{dispatchEvent:x=>observations.push(x.type)},
 CustomEvent:class{constructor(type){this.type=type}},
 monitorNativePending:[{resolve:x=>first.push(x)}],
 monitorCoreNativePending:[{resolve:x=>second.push(x)}],
 monitorDesktopThumbs:{dataset:{},querySelectorAll:()=>[visual]},
 MONITOR_WALLPAPER_MAX_WIDTH:960,MONITOR_WALLPAPER_MAX_HEIGHT:600,
 monitorNative:async req=>({ok:true,desktopId:req.desktopId}),
 monitorBctPointerDrag:null,monitorBctNativePreviewToken:"",handleMonitorForegroundChangedEvent:()=>{},
 scheduleMonitorWindowLifecycleEvent:()=>{},
 cancelMonitorBctNodePointerDrag:()=>{},
 globalThis:null
};
globals.globalThis=globals;
globals.MonitorDesktopThumbnailV2={
 refreshWallpaper:(tile,id)=>{observations.push("wallpaper:"+id);return Promise.resolve(true)}
};
vm.createContext(globals);
const f1=vm.runInContext("(function(response){"+relevant.find(x=>x.includes("monitorNativePending.shift()"))+"\n})",globals);
const f2=vm.runInContext("(function(response){"+relevant.find(x=>x.includes("monitorCoreNativePending.shift()"))+"\n})",globals);
f1({event:true,type:"desktopWallpaperChanged"});
assert.equal(globals.monitorNativePending.length,1,"wallpaper event on visual port never consumes reply");
f1({event:true,type:"unexpectedFutureNativeSignal"});
assert.equal(globals.monitorNativePending.length,1,"unknown event cannot consume visual port reply");
f2({event:true,type:"desktopWallpaperChanged"});
assert.equal(globals.monitorCoreNativePending.length,1,"wallpaper event on second Core port never consumes reply");
f2({event:true,type:"windowMoveSizeEnd"});
assert.equal(globals.monitorCoreNativePending.length,1,"window move event cannot consume Core reply");
f2({event:true,type:"shellMirrorChanged"});
assert.equal(globals.monitorCoreNativePending.length,1,"shell subscription stays separate");
assert(observations.includes("desktopwindow-shell-native-event"));
const a={ok:true,desktopId:visual.dataset.desktopId},b={ok:true,command:"getDesktopWindows"};
f1(a);f2(b);
assert.deepEqual(first,[a]);assert.deepEqual(second,[b]);
assert.equal(globals.monitorNativePending.length,0);
assert.equal(globals.monitorCoreNativePending.length,0);
console.log("PASS: both persistent Monitor native ports ignore unsolicited events, preserve shell mirror and deliver exact request replies");
