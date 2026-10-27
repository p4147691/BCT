"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");

const root=path.resolve(__dirname,"..");
const read=relative=>fs.readFileSync(path.join(root,relative),"utf8");
const native=read("native/src/MonitorDesktopHost.cs");
const backgroundState=read("native/src/DesktopBackgroundStateSource.cs");
const visual=read("native/src/DesktopVisualSnapshot.cs");
const lifecycle=read("domains/desktop-lifecycle.js");
const wallpaper=read("domains/thumbnail-wallpaper.js");
const composition=[
  read("extension/monitor-thumbnail-contract.js"),
  read("extension/monitor-thumbnail-background-layer.js"),
  read("extension/monitor-desktop-thumbnail-v2.js")
].join("\n");

function nativeMethod(name,nextName){
  const start=native.indexOf(`private static object ${name}`);
  const end=native.indexOf(`private static object ${nextName}`,start+1);
  assert.ok(start>=0&&end>start,`native method boundary missing: ${name}`);
  return native.slice(start,end);
}

assert.doesNotMatch(native,/SetDesktopWallpaperPath|SetValue\("Wallpaper"/,
  "Native Monitor must not write Windows wallpaper state");
assert.doesNotMatch(nativeMethod("CreateVirtualDesktop","RemoveVirtualDesktop"),
  /DesktopBackgroundStateSource|GetDesktopWallpaperPath|SetWallpaper|wallpaperPath/i,
  "desktop creation must leave personalization to Windows");
assert.doesNotMatch(nativeMethod("RestoreVirtualDesktop","MoveWindowToDesktop"),
  /GetDesktopWallpaperPath|SetWallpaper|wallpaperPath/i,
  "desktop restore must recreate desktop/windows without restoring personalization");

assert.match(backgroundState,/TryGet\(out DesktopGlobalBackgroundState state\)/);
assert.doesNotMatch(backgroundState,/GetPixel\(|BackgroundType|CurrentVirtualDesktop|VirtualDesktopIDs|Registry\./,
  "background mode must not use registry or screen-pixel heuristics");
assert.doesNotMatch(backgroundState,/api\.SetWallpaper\(|api\.SetBackgroundColor\(/,
  "read-only COM adapter must never invoke setter slots");
assert.match(visual,/IsActiveDesktop\(desktopId\)/);
assert.match(visual,/DesktopBackgroundStateSource\.TryGet/);
assert.match(visual,/ColorTranslator\.FromHtml\(backgroundState\.BaseColor\)/,
  "photo composition must preserve the Windows base color under Fit/Center images");

assert.doesNotMatch(composition,/inheritBackground|inheritedWallpaper/,
  "new tiles must not inherit remembered wallpaper state");
assert.doesNotMatch(lifecycle,/restoreVirtualDesktop[^\n]+wallpaperPath/,
  "restore requests must not carry a wallpaper write payload");
assert.match(wallpaper,/renderer\?\.refreshBackground\?\.\(visual,createdId,\{forceWallpaper:true\}\)/,
  "new desktops must settle by fresh Native-backed V2 reads");

console.log("PASS: Monitor wallpaper path is read-only and new/restored desktops use fresh Windows state");
