"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path");
const ext=path.join(__dirname,"../extension");
const monitor=fs.readFileSync(path.join(ext,"monitor.js"),"utf8");
const v2=fs.readFileSync(path.join(ext,"monitor-desktop-thumbnail-v2.js"),"utf8");
const background=fs.readFileSync(path.join(ext,"monitor-thumbnail-background-layer.js"),"utf8");
const windows=fs.readFileSync(path.join(ext,"monitor-thumbnail-window-layer.js"),"utf8");
const html=fs.readFileSync(path.join(ext,"desktop.html"),"utf8");

// This is an architectural fail-closed gate, not a cosmetic regression test.
// Old thumbnail screenshot/cache paths must never regain DOM write authority.
const ordered=["monitor-thumbnail-contract.js","monitor-desktop-visual-source.js","monitor-thumbnail-layer-policy.js","monitor-thumbnail-background-layer.js","monitor-thumbnail-window-layer.js","monitor-desktop-thumbnail-v2.js","monitor.js"];
let previous=-1;
for(const name of ordered){
 const position=html.indexOf('<script src="'+name+'"></script>');
 assert(position>previous,name+" must load in architectural dependency order");
 previous=position;
}
assert.doesNotMatch(html,/monitor-wallpaper-event-refresh\.js/);
assert.match(monitor,/function scheduleMonitorV2WindowRefresh\(event\)/);
assert.match(monitor,/function removeMonitorV2Window\(hwnd, exceptDesktopId = ""\)/);
assert.match(monitor,/globalThis\.MonitorDesktopThumbnailV2\.refreshBackground\(/);
assert.match(monitor,/renderer\.refresh\(visual,desktopId\)/);
assert.doesNotMatch(monitor,/renderer\.refreshWallpaper\(|renderer\.beginFrame\(|renderer\.windowFrame\(|renderer\.frameFailure\(/,
  "the compatibility bundle must not orchestrate V2 layers");
assert.doesNotMatch(monitor,/function upsertMonitorEventThumbWindow\(/);
assert.doesNotMatch(monitor,/function removeMonitorEventThumbWindow\(/);
assert.doesNotMatch(monitor,/visual\.style\.backgroundImage\s*=/);
assert.doesNotMatch(monitor,/img\.className\s*=\s*["']monitor-desktop-thumb-window["']/);
assert.doesNotMatch(monitor,/\.monitor-desktop-thumb-window[^;\n]+\.src\s*=/);
assert.doesNotMatch(monitor,/monitorWindowFallbackDataUri\(event\)/);
assert.doesNotMatch(monitor,/if\s*\(dataUri\)\s*img\.src/);
assert.doesNotMatch(monitor,/document\.querySelectorAll\([^;\n]+\.monitor-desktop-thumb-window[^;\n]+\)\s*\)\s*apply\(img\)/);
assert.match(v2,/backgrounds\.create\(\{contract,visualSource\}\)/);
assert.match(v2,/windows\.create\(\{contract\}\)/);
assert.match(v2,/policy\.allows\("windows"\)/);
assert.doesNotMatch(v2,/backgroundImage\s*=|createElement\("img"\)/,
  "the compositor must not steal layer implementation details");
assert.match(background,/visual\.style\.backgroundImage = "url\("/);
assert.doesNotMatch(background,/createElement\("img"\)|monitor-desktop-thumb-window/);
assert.match(windows,/function removeWindow\(visual,\s*desktopId,\s*hwnd\)/);
assert.match(windows,/function beginFrame\(visual,\s*desktopId\)/);
assert.match(windows,/state\.generation!==bindings\.frameToken/);
assert.match(windows,/state\.generation!==frameToken/);
assert.doesNotMatch(windows,/backgroundImage\s*=|backgroundColor\s*=/);
console.log("PASS: background pixels, HWND pixels and composition have separate owners; old direct writers remain absent");
