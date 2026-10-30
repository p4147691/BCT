 "use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname,"../domains/shared-ui.js"),"utf8");
const background = fs.readFileSync(path.join(__dirname,"../extension/background.js"),"utf8");
assert.match(background,/chrome\.windows\.onCreated\.addListener\(\(windowInfo\)/,
  "new Chrome normal windows must publish a direct event");
assert.match(background,/publishMonitorBrowserWindowVisualChange\(windowInfo\.id, "window-created"\)/);
assert.match(background,/chrome\.tabs\.onCreated\.addListener/);
const extract=(name)=>{
 const start=source.indexOf("//@@FN_START:"+name);
 const end=source.indexOf("//@@FN_END:"+name,start);
 assert.ok(start>=0&&end>start,name);
 return source.slice(source.indexOf(String.fromCharCode(10),start)+1,end);
};
let rosterReads=0,visualRefreshes=0;
const timers=[];
const context={
 monitorBrowserVisualPendingWindowIds:new Set(),
 monitorBrowserVisualRefreshInFlight:false,
 monitorBrowserVisualRefreshTimer:0,
 monitorBrowserRosterRefreshPending:false,
 MONITOR_BROWSER_VISUAL_REFRESH_DEBOUNCE_MS:120,
 applyMonitorBrowserVisualTabSnapshot:()=>false,
 monitorHwndForBrowserWindowId:()=>"",
 monitorObservedState:{snapshot:()=>({})},
 monitorWindowDesktopLocations:new Map(),
 monitorDesktopIdentityState:{snapshot:()=>({desktopIds:["desktop-1"],selectedIndex:0})},
 monitorThumbnailService:{invalidate:()=>{}},
 invalidateMonitorDesktopFrames:()=>{},
 refreshSelectedThumb:async()=>{visualRefreshes++;return true;},
 refreshBackgroundThumbs:async()=>[],
 refreshMonitorBctWindowNodes:async()=>{rosterReads++;},
 syncMonitorAllDesktopThumbnailNodeBadges:()=>{},
 setTimeout(fn){timers.push(fn);return timers.length;},
 clearTimeout:()=>{},
 console,Map,Set,Array,Number,String,Boolean,
};
vm.createContext(context);
vm.runInContext(extract("flushMonitorBrowserVisualRefresh")+"\n"+extract("scheduleMonitorBrowserVisualRefresh"),context);
(async()=>{
 context.scheduleMonitorBrowserVisualRefresh({windowId:11,reason:"window-created"});
 context.scheduleMonitorBrowserVisualRefresh({windowId:11,reason:"tab-created"});
 await context.flushMonitorBrowserVisualRefresh();
 assert.equal(rosterReads,1,"new window + tab creation coalesce into one RCC/Monitor roster read");
 assert.equal(visualRefreshes,1,"Native visual frame is refreshed");
 context.scheduleMonitorBrowserVisualRefresh({windowId:11,reason:"tab-activated"});
 await context.flushMonitorBrowserVisualRefresh();
 assert.equal(rosterReads,1,"tab-only activation must not cause extra roster traffic");
 context.scheduleMonitorBrowserVisualRefresh({windowId:11,reason:"window-removed"});
 await context.flushMonitorBrowserVisualRefresh();
 assert.equal(rosterReads,2,"window removal must update roster without focus");
 console.log("PASS: Chrome create/remove events coalesce immediate roster refresh, no polling/focus");
})().catch(e=>{console.error(e);process.exitCode=1;});
