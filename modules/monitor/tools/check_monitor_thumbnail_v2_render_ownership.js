"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path");
const ext=path.join(__dirname,"../extension");
const monitor=fs.readFileSync(path.join(ext,"monitor.js"),"utf8");
const v2=fs.readFileSync(path.join(ext,"monitor-desktop-thumbnail-v2.js"),"utf8");
const html=fs.readFileSync(path.join(ext,"desktop.html"),"utf8");

// This is an architectural fail-closed gate, not a cosmetic regression test.
// Old thumbnail screenshot/cache paths must never regain DOM write authority.
assert.match(html,/<script src="monitor-desktop-thumbnail-v2.js"><\/script>/);
assert.doesNotMatch(html,/monitor-wallpaper-event-refresh\.js/);
assert.match(monitor,/function scheduleMonitorV2WindowRefresh\(event\)/);
assert.match(monitor,/function removeMonitorV2Window\(hwnd, exceptDesktopId = ""\)/);
assert.match(monitor,/globalThis\.MonitorDesktopThumbnailV2\.refreshWallpaper\(/);
assert.match(monitor,/renderer\.beginFrame\(visual,desktopId\)/);
assert.match(monitor,/renderer\.windowFrame\(visual,desktopId,frame,/);
assert.doesNotMatch(monitor,/function upsertMonitorEventThumbWindow\(/);
assert.doesNotMatch(monitor,/function removeMonitorEventThumbWindow\(/);
assert.doesNotMatch(monitor,/visual\.style\.backgroundImage\s*=/);
assert.doesNotMatch(monitor,/img\.className\s*=\s*["']monitor-desktop-thumb-window["']/);
assert.doesNotMatch(monitor,/\.monitor-desktop-thumb-window[^;\n]+\.src\s*=/);
assert.doesNotMatch(monitor,/monitorWindowFallbackDataUri\(event\)/);
assert.doesNotMatch(monitor,/if\s*\(dataUri\)\s*img\.src/);
assert.doesNotMatch(monitor,/document\.querySelectorAll\([^;\n]+\.monitor-desktop-thumb-window[^;\n]+\)\s*\)\s*apply\(img\)/);
assert.match(v2,/function removeWindow\(visual, desktopId, hwnd\)/);
assert.match(v2,/function beginFrame\(visual, desktopId\)/);
assert.match(v2,/frameGeneration !== bindings\.frameToken/);
assert.match(v2,/frameGeneration !== frameToken/);
assert.match(v2,/backgroundImage = "url\("/);
console.log("PASS: only V2 writes bottom thumbnail pixels, old window event/cache writers are absent; legacy preview remains separate");
