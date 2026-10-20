"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function load(relativePath, context) {
  const source = fs.readFileSync(path.join(__dirname, "..", "extension", relativePath), "utf8");
  vm.runInContext(source, context);
}

const context = {
  globalThis: null,
  fetch: async () => { throw new Error("network must not be used"); },
  chrome: { windows: {} },
  crypto: { randomUUID: () => "test" },
  Map, Set, Object, String, Number, Array, Date,
};
context.globalThis = context;
vm.createContext(context);
load("monitor-bct-shell.js", context);
load("monitor-window-hwnd-contract.js", context);

const shell = context.MonitorBctShell.create();
const contract = context.MonitorWindowHwndContract.create({ identityMaxAgeMs: 8000, locationMaxAgeMs: 5000 });
const now = 100000;
const openState = {
  rcc: { instances: [{
    instance_id: "rcc-live",
    session_id: "session-live",
    state: "OPEN",
    tabs: [
      { tab_id: 4, window_id: 594834491, title: "N4", url: "https://chatgpt.com/c/chat-four", node_label: "N4", active: true },
      { tab_id: 7, window_id: 594834491, title: "N7", url: "https://chatgpt.com/c/chat-seven", node_label: "N7", active: false },
      { tab_id: 9, window_id: 594834491, title: "N9", url: "https://chatgpt.com/c/chat-nine", node_label: "N9", active: false },
    ],
  }] },
};
const openNodes = shell.windowNodes(openState);
const locations = new Map([["777", {
  hwnd: "777", className: "Chrome_WidgetWin_1", conversationKey: "chat-four",
  identityAt: now - 100, at: now - 100,
}]]);
const initial = contract.resolve({ nodes: openNodes, locations, now });
assert.equal(initial.bindings.length, 1);
assert.equal(initial.bindings[0].hwnd, "777");

function projectedLabel(nodes, bindings) {
  const hwndByLineage = new Map(bindings.map((binding) => [binding.lineage, binding.hwnd]));
  const labels = nodes.filter((node) => {
    const lineage = `${node.instanceId}:${node.sessionId}:${node.windowId}`;
    return hwndByLineage.get(lineage) === "777";
  }).map((node) => Number(String(node.nodeLabel).replace(/^N/i, ""))).filter(Number.isFinite);
  return `N${[...new Set(labels)].sort((a, b) => a - b).join("/")}`;
}

assert.equal(projectedLabel(openNodes, initial.bindings), "N4/7/9");

const unavailableState = {
  rcc: { instances: [{ instance_id: "rcc-live", state: "UNAVAILABLE", error: "TimeoutError", tabs: [] }] },
};
const cachedNodes = shell.displayWindowNodes(unavailableState, openNodes);
assert.equal(cachedNodes.length, 3);
assert.equal(contract.resolve({ nodes: cachedNodes, locations, now }).bindings.length, 0,
  "stale display nodes cannot establish a new HWND mapping");
const retained = contract.retainCurrentSessionBindings({
  bindings: [], previousBindings: initial.bindings, nodes: cachedNodes, locations, now,
});
assert.equal(projectedLabel(cachedNodes, retained), "N4/7/9",
  "a transient RCC miss preserves the prior exact N4/7/9 projection while Native still sees the same HWND");

const expired = contract.retainCurrentSessionBindings({
  bindings: [], previousBindings: initial.bindings, nodes: cachedNodes,
  locations: new Map([["777", { hwnd: "777", className: "Chrome_WidgetWin_1", at: now - 6000 }]]), now,
});
assert.equal(expired.length, 0, "stale Native evidence must remove the retained mapping");
assert.equal(contract.retainCurrentSessionBindings({
  bindings: [], previousBindings: [], nodes: cachedNodes, locations, now,
}).length, 0, "cached RCC data must never fabricate a first binding");

console.log("PASS: actual shell + HWND contract keeps N4/7/9 only across a transient RCC miss with a fresh prior exact HWND");
