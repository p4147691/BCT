"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const root=path.join(__dirname,"..");
const transport=fs.readFileSync(path.join(root,"domains","native-transport.js"),"utf8");
const lifecycle=fs.readFileSync(path.join(root,"source-parts","05-native-lifecycle.js"),"utf8");
const host=fs.readFileSync(path.join(root,"native","src","MonitorDesktopHost.cs"),"utf8");

assert.match(lifecycle,/const monitorNativePending = new Map\(\)/,"Control requests require keyed ownership");
assert.match(lifecycle,/MonitorDesktopVisualSource\.create\(\{ request: monitorNative \}\)/,
  "desktop visual source must receive the canonical Control transport");
assert.match(lifecycle,/MonitorDesktopThumbnailV2\.configure\(\{[\s\S]*?visualSource: monitorDesktopVisualSource,[\s\S]*?readFrame: desktopId => captureDesktopFrame\(desktopId, "thumb"\),[\s\S]*?afterWindowRender: decorateMonitorThumbnailWindows,/);
assert.match(transport,/if \(response\?\.event === true\) return;/,
  "unsolicited Native events cannot complete a request");
assert.match(transport,/const requestId = String\(response\?\.requestId \|\| ""\)/);
assert.match(transport,/monitorNativePending\.get\(requestId\)/);
assert.match(transport,/monitorNativePending\.delete\(requestId\)/);
assert.match(transport,/port\.postMessage\(\{ \.\.\.message, requestId \}\)/);
assert.doesNotMatch(transport,/monitorNativePending\.shift\(\)/,
  "Control replies must never be assigned by FIFO arrival order");
assert.match(host,/request\.TryGetValue\("requestId", out requestId\)/);
assert.match(host,/responseMap\["requestId"\] = Convert\.ToString\(requestId\)/,
  "the Native host must echo the exact correlation id");

console.log("PASS: one persistent Control port correlates replies by requestId while unsolicited events remain independent");
