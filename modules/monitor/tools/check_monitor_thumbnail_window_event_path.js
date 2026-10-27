"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path");
const root=path.join(__dirname,"..");
const lifecycle=fs.readFileSync(path.join(root,"domains","diagnostics-shell.js"),"utf8");
const start=lifecycle.indexOf("async function handleMonitorWindowLifecycleEvent(event)");
const end=lifecycle.indexOf("//@@FN_END:handleMonitorWindowLifecycleEvent",start);
assert(start>=0&&end>start,"lifecycle handler must exist");
const body=lifecycle.slice(start,end);
assert.match(body,/MonitorDesktopThumbnailV2\?\.windowEvent\?\.\(eventVisual,desktopId,event\)/,
  "native location data must update the V2 HWND geometry directly");
assert.doesNotMatch(body,/await\s+refreshSelectedThumb\s*\(/,
  "a location event must not wait for a full selected-desktop WGC refresh");
assert.match(body,/if\s*\(selectedDesktop\)\s*\{\s*scheduleMonitorV2WindowRefresh\(event\)/,
  "selected-desktop pixels must refresh in the independent coalesced path");
const missingId=body.slice(body.indexOf("if (!desktopId)"),body.indexOf("const previousDesktopId"));
assert.doesNotMatch(missingId,/await\s+refreshDesktopThumb/,
  "an unidentified event must not serialize every desktop behind full capture");
console.log("PASS: lifecycle events apply HWND geometry immediately and never block the event drain on WGC pixel refresh");
