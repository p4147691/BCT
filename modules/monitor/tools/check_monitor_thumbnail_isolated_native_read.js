"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const root=path.join(__dirname,"..");
const transport=fs.readFileSync(path.join(root,"domains","native-transport.js"),"utf8");
const wallpaper=fs.readFileSync(path.join(root,"domains","thumbnail-wallpaper.js"),"utf8");
const lifecycle=fs.readFileSync(path.join(root,"source-parts","05-native-lifecycle.js"),"utf8");
const visualSource=fs.readFileSync(path.join(root,"extension","monitor-desktop-visual-source.js"),"utf8");

assert.doesNotMatch(transport,/function monitorNativeVisualRead\(/);
assert.doesNotMatch(transport,/sendNativeMessage\(MONITOR_CONTROL_HOST/,
  "thumbnail reads must not open a side-channel Native request");
assert.match(transport,/function monitorControlNativeRequest\(message\)/);
assert.match(lifecycle,/MonitorDesktopVisualSource\.create\(\{ request: monitorWallpaperNativeRequest \}\)/,
  "wallpaper snapshots use the dedicated correlated Native port");
assert.match(visualSource,/return await request\(\{/);
assert.match(visualSource,/type:"getDesktopVisualSnapshot"/);
assert.doesNotMatch(visualSource,/\bchrome\b|connectNative|sendNativeMessage/,
  "the source adapter depends only on its injected request port");
assert.doesNotMatch(wallpaper,/monitorNativeVisualRead\(/);

console.log("PASS: wallpaper snapshots use the canonical correlated Native port through an injected DesktopVisualSource");
