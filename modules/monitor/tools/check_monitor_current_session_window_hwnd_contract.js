"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "..", "extension", "monitor-window-hwnd-contract.js"), "utf8");
const desktopSource = fs.readFileSync(path.join(__dirname, "..", "extension", "desktop.html"), "utf8");
const monitorSource = fs.readFileSync(path.join(__dirname, "..", "extension", "monitor.js"), "utf8");
const context = { globalThis: null, Map, Set, Object, String, Number, Array, Date }; context.globalThis = context; vm.createContext(context); vm.runInContext(source, context);
const contract = context.MonitorWindowHwndContract.create({ identityMaxAgeMs: 8000 }), now = 100000;
const nodes = [
  { instanceId: "rcc-a", sessionId: "session-a", instanceState: "OPEN", windowId: 11, tabId: 1, active: true, conversationKey: "chat-one" },
  { instanceId: "rcc-a", sessionId: "session-a", instanceState: "OPEN", windowId: 11, tabId: 2, active: false, conversationKey: "chat-two" },
  { instanceId: "rcc-a", sessionId: "session-a", instanceState: "OPEN", windowId: 12, tabId: 3, active: true, conversationKey: "chat-three" },
];
const locations = new Map([["500", { hwnd: "500", conversationKey: "chat-one", identityAt: now - 100 }], ["600", { hwnd: "600", conversationKey: "chat-three", identityAt: now - 100 }]]);
let resolution = contract.resolve({ nodes, locations, now });
assert.deepEqual(Array.from(resolution.bindings, (row) => [row.lineage, row.hwnd]), [["rcc-a:session-a:11", "500"], ["rcc-a:session-a:12", "600"]]);
const retained = contract.retainCurrentSessionBindings({
  bindings: [], previousBindings: resolution.bindings,
  nodes: nodes.map((node) => ({ ...node, active: false })),
  locations: new Map([["500", { hwnd: "500", className: "Chrome_WidgetWin_1", at: now - 100 }], ["600", { hwnd: "600", className: "Chrome_WidgetWin_1", at: now - 100 }]]), now,
});
assert.deepEqual(Array.from(retained, (row) => [row.lineage, row.hwnd]), [["rcc-a:session-a:11", "500"], ["rcc-a:session-a:12", "600"]]);
const cachedUnavailableNodes = nodes.map((node) => ({
  ...node, instanceState: "UNAVAILABLE", instanceCached: true, lastKnownState: "OPEN",
}));
assert.equal(contract.resolve({ nodes: cachedUnavailableNodes, locations, now }).bindings.length, 0,
  "a cached RCC row must never create a new HWND binding");
assert.deepEqual(Array.from(contract.retainCurrentSessionBindings({
  bindings: [], previousBindings: resolution.bindings,
  nodes: cachedUnavailableNodes,
  locations: new Map([["500", { hwnd: "500", className: "Chrome_WidgetWin_1", at: now - 100 }], ["600", { hwnd: "600", className: "Chrome_WidgetWin_1", at: now - 100 }]]), now,
}), (row) => [row.lineage, row.hwnd]), [["rcc-a:session-a:11", "500"], ["rcc-a:session-a:12", "600"]]);
assert.equal(contract.retainCurrentSessionBindings({
  bindings: [], previousBindings: resolution.bindings,
  nodes: cachedUnavailableNodes.map((node) => ({ ...node, instanceCached: false })),
  locations: new Map([["500", { hwnd: "500", className: "Chrome_WidgetWin_1", at: now - 100 }]]), now,
}).length, 0, "an unverified unavailable RCC row must not retain a binding");
assert.equal(contract.retainCurrentSessionBindings({
  bindings: [], previousBindings: resolution.bindings, nodes,
  locations: new Map([["500", { hwnd: "500", className: "Chrome_WidgetWin_1", at: now - 6000 }]]), now,
}).length, 0);
resolution = contract.resolve({ nodes: [...nodes, { instanceId: "rcc-a", sessionId: "session-a", instanceState: "OPEN", windowId: 13, tabId: 4, active: true, conversationKey: "chat-one" }], locations, now });
assert.equal(resolution.bindings.length, 1); assert.ok(resolution.rejected.some((row) => row.reason === "RCC_WINDOW_AMBIGUOUS"));
resolution = contract.resolve({ nodes, locations: new Map([["500", { hwnd: "500", conversationKey: "chat-one", identityAt: now - 100 }], ["501", { hwnd: "501", conversationKey: "chat-one", identityAt: now - 100 }], ["600", { hwnd: "600", conversationKey: "chat-three", identityAt: now - 9000 }]]), now });
assert.equal(resolution.bindings.length, 0); assert.ok(resolution.rejected.some((row) => row.reason === "HWND_AMBIGUOUS")); assert.ok(resolution.rejected.some((row) => row.reason === "HWND_IDENTITY_UNAVAILABLE"));
resolution = contract.resolve({ nodes: [{ ...nodes[0], active: false }], locations, now }); assert.equal(resolution.bindings.length, 0);
assert.ok(desktopSource.indexOf("monitor-window-hwnd-contract.js") < desktopSource.indexOf("monitor.js"));
assert.match(monitorSource, /refreshMonitorBctCurrentSessionWindowHwnd\(\)/);
assert.match(monitorSource, /monitorBctCurrentSessionHwnd\(windowId/);
assert.match(monitorSource, /monitorWindowHwndContract\?\.resolve/);
assert.match(monitorSource, /retainCurrentSessionBindings/);
console.log("PASS: current-session RCC Chrome window_id to HWND contract rejects stale/ambiguous identity and retains only a freshly observed physical window across tab selection");
