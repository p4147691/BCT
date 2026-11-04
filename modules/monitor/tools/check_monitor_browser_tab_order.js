"use strict";

// Isolated contract: a Chrome tab-order snapshot must update the thumbnail
// projection without a Monitor focus event or a Core membership reload.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function domainFunction(file, name) {
  const source = fs.readFileSync(path.join(__dirname, "../domains", file), "utf8");
  const match = source.match(new RegExp(`//@@FN_START:${name}\\n([\\s\\S]*?)\\n//@@FN_END:${name}`));
  assert.ok(match, `${name} must remain in its owned domain`);
  return match[1];
}

const context = {
  Map, Set, Number, String, Array, URL,
  monitorLastAiState: {},
  monitorBrowserVisualTabsByWindow: new Map(),
  monitorBctWindowNodesCache: [
    { windowId: 41, tabId: 101, tabIndex: 0, nodeLabel: "N32" },
    { windowId: 41, tabId: 102, tabIndex: 1, nodeLabel: "N35" },
    { windowId: 41, tabId: 103, tabIndex: 2, nodeLabel: "N37" },
    { windowId: 41, tabId: 105, tabIndex: 4, nodeLabel: "N38" },
  ],
  monitorBctDisplaySessionHwnd: () => "900",
  monitorWindowHwndContract: { resolve: () => ({ bindings: [] }) },
  monitorWindowDesktopLocations: new Map(),
  monitorActNodeNumbersForHwnd: () => [],
  Date,
};
vm.createContext(context);
vm.runInContext([
  domainFunction("shared-ui.js", "applyMonitorBrowserVisualTabSnapshot"),
  domainFunction("shared-ui.js", "monitorBrowserVisualTabsForWindow"),
  domainFunction("node-identity.js", "monitorBadgeNodeNumbersForHwnd"),
].join("\n"), context);

assert.equal(context.applyMonitorBrowserVisualTabSnapshot({
  windowId: 41,
  tabs: [
    { tabId: 101, tabIndex: 0 },
    { tabId: 102, tabIndex: 1 },
    { tabId: 103, tabIndex: 2 },
    { tabId: 104, tabIndex: 3, url: "https://chatgpt.com/" },
    { tabId: 106, tabIndex: 4, url: "https://www.youtube.com/watch?v=test" },
    { tabId: 105, tabIndex: 5 },
  ],
}), true);
assert.deepEqual(
  Array.from(context.monitorBadgeNodeNumbersForHwnd("900")),
  [32, 35, 37, "?", 38],
  "a UUID-less tab remains in its physical Chrome position as N?",
);

assert.equal(context.applyMonitorBrowserVisualTabSnapshot({
  windowId: 41,
  tabs: [
    { tabId: 105, tabIndex: 0 },
    { tabId: 101, tabIndex: 1 },
    { tabId: 102, tabIndex: 2 },
    { tabId: 103, tabIndex: 3 },
    { tabId: 106, tabIndex: 4, url: "https://www.youtube.com/watch?v=test" },
    { tabId: 104, tabIndex: 5, url: "https://chatgpt.com/" },
  ],
}), true);
assert.deepEqual(
  Array.from(context.monitorBadgeNodeNumbersForHwnd("900")),
  [38, 32, 35, 37, "?"],
  "a tab move immediately changes the projection order without a Core refresh",
);

console.log("PASS: observed Chrome tab order preserves N? and updates thumbnail order without Monitor focus");
