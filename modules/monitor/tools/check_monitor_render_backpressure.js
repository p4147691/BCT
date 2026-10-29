"use strict";

// The Monitor page may receive a burst of Chrome tab/focus events while a
// desktop thumbnail capture is still running. Keep this small test isolated
// from the DOM and assert that the page serializes those refreshes.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../extension/monitor.js"), "utf8");
const start = source.indexOf("const monitorBrowserVisualPendingWindowIds = new Set();");
const end = source.indexOf("\nfunction scheduleMonitorChatNavigationRefresh(", start);
assert(start >= 0 && end > start, "browser visual backpressure block");
const block = source.slice(start, end);

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let selectedRefreshes = 0;
let activeRefreshes = 0;
let maxActiveRefreshes = 0;
let releaseFirst;
const firstGate = new Promise((resolve) => { releaseFirst = resolve; });
const invalidatedHwnds = [];

const context = {
  Set,
  Map,
  String,
  Number,
  Array,
  Boolean,
  setTimeout,
  clearTimeout,
  monitorObservedState: {snapshot:()=>({})},
  monitorDesktopIdentityState: { snapshot:()=>({ desktopIds: ["D1"], selectedIndex: 0, hostDesktopId: "D1", currentDesktopId: "D1" }) },
  monitorWindowDesktopLocations: new Map([["100", { desktopId: "D1" }]]),
  monitorHwndForBrowserWindowId: () => "100",
  monitorThumbnailService: { invalidate: (hwnd) => invalidatedHwnds.push(String(hwnd)) },
  syncMonitorAllDesktopThumbnailNodeBadges: () => {},
  invalidateMonitorDesktopFrames: () => {},
  refreshBackgroundThumbs: async () => [],
  refreshObservedWindows: async () => true,
  refreshSelectedThumb: async () => {
    selectedRefreshes += 1;
    activeRefreshes += 1;
    maxActiveRefreshes = Math.max(maxActiveRefreshes, activeRefreshes);
    if (selectedRefreshes === 1) await firstGate;
    activeRefreshes -= 1;
    return true;
  }
};

vm.createContext(context);
vm.runInContext(block, context);

(async () => {
  context.scheduleMonitorBrowserVisualRefresh({ windowId: 1 });
  context.scheduleMonitorBrowserVisualRefresh({ windowId: 1 });
  await wait(400);
  assert.equal(selectedRefreshes, 1, "first event burst is coalesced");
  context.scheduleMonitorBrowserVisualRefresh({ windowId: 2 });
  await wait(25);
  assert.equal(selectedRefreshes, 1, "a new burst waits for the in-flight refresh");
  releaseFirst();
  await wait(420);
  assert.equal(selectedRefreshes, 2, "pending burst receives one trailing refresh");
  assert.equal(maxActiveRefreshes, 1, "desktop refreshes never overlap");
  assert.deepEqual(invalidatedHwnds, ["100", "100"], "each merged burst invalidates exactly once");
  assert.match(source, /const maxConcurrent = 1;/, "native WGC captures are serialized");
  assert.match(source, /scheduleMonitorPopupTopologyRefresh\(desktopIds\);/, "topology events use the same backpressure boundary");
  console.log("PASS: Monitor browser/topology thumbnail refreshes are coalesced and serialized");
})().catch((error) => {
  console.error(error?.stack || error);
  process.exitCode = 1;
});
