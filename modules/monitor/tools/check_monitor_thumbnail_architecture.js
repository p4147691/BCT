"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const ext=path.join(__dirname,"..","extension");
const names=[
  "monitor-thumbnail-contract.js",
  "monitor-preview-background.js",
  "monitor-desktop-visual-source.js",
  "monitor-thumbnail-layer-policy.js",
  "monitor-thumbnail-background-layer.js",
  "monitor-thumbnail-window-layer.js",
  "monitor-desktop-thumbnail-v2.js"
];
const sources=Object.fromEntries(names.map(name=>[name,fs.readFileSync(path.join(ext,name),"utf8")]));
for(const [name,source] of Object.entries(sources)){
  assert.doesNotMatch(source,/sendNativeMessage|connectNative|MONITOR_CONTROL_HOST|monitorWallpaperCache|monitorWallpaperActuals/,
    name+" must depend on a narrow injected contract, not application globals");
}
assert.doesNotMatch(sources["monitor-desktop-visual-source.js"],/document|createElement|backgroundImage|backgroundColor/);
assert.doesNotMatch(sources["monitor-thumbnail-contract.js"],/document|chrome|style\./);
assert.doesNotMatch(sources["monitor-preview-background.js"],/chrome|connectNative|getDesktopVisualSnapshot|monitor-desktop-thumb/);
assert.doesNotMatch(sources["monitor-thumbnail-background-layer.js"],/createElement|\.src\s*=|monitor-desktop-thumb-window/);
assert.doesNotMatch(sources["monitor-thumbnail-window-layer.js"],/backgroundImage\s*=|backgroundColor\s*=/);

const context={globalThis:null,Object,String,Number,RegExp,TypeError};
context.globalThis=context;vm.createContext(context);
vm.runInContext(sources["monitor-thumbnail-contract.js"],context);
const contract=context.MonitorThumbnailContract;
const D1="8ac6b16f-820b-4773-89e7-276ae4b84040";
assert.deepEqual(
  JSON.parse(JSON.stringify(contract.wallpaperSnapshot(D1,{ok:true,desktopId:D1,wallpaper:{mode:"solid",color:"#10893e",proof:"windows-solid-mode"}}))),
  {ok:true,kind:"solid",desktopId:D1,color:"#10893E",proof:"windows-solid-mode"}
);
assert.equal(contract.wallpaperSnapshot(D1,{ok:true,desktopId:D1,wallpaper:{mode:"solid",color:"gray"}}).ok,false);
assert.equal(contract.wallpaperSnapshot(D1,{ok:true,desktopId:D1,wallpaper:{dataUri:"data:image/svg+xml;base64,FAKE"}}).ok,false);
assert.equal(contract.wallpaperSnapshot(D1,{ok:true,desktopId:"c991b275-7933-4697-9d6e-73bf31ae4379",wallpaper:{mode:"solid",color:"#10893E"}}).ok,false);

console.log("PASS: thumbnail ports and layers are isolated, and only exact GUID photo/solid evidence reaches rendering");
