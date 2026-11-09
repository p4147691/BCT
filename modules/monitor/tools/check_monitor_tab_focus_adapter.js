"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const adapterPath = path.join(__dirname, "..", "extension", "browser", "tab-focus-adapter.js");
const backgroundPath = path.join(__dirname, "..", "extension", "background.js");
const monitorPath = path.join(__dirname, "..", "extension", "monitor.js");

function loadAdapter() {
  const context = { globalThis: null, Object, String, Number, URL, RegExp, Promise };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(adapterPath, "utf8"), context, { filename: adapterPath });
  return context.MonitorTabFocusAdapter;
}

(async () => {
  const target = { tabId: 17, windowId: 33, conversationKey: "6ad733b6-95d4-83ee-b4ba-49a671229d77" };
  const calls = [];
  const tab = { id: 17, windowId: 33, url: `https://chatgpt.com/c/${target.conversationKey}`, active: false };
  const chromeApi = {
    tabs: {
      get: async (tabId) => ({ ...tab, id: tabId }),
      update: async (tabId, update) => {
        calls.push(["tab", tabId, update]);
        tab.active = update.active === true;
        return { ...tab };
      },
    },
    windows: {
      update: async (windowId, update) => {
        calls.push(["window", windowId, update]);
        return { id: windowId, focused: true };
      },
      get: async (windowId) => ({ id: windowId, focused: true }),
    },
  };
  const applied = await loadAdapter().create(chromeApi).focus(target);
  assert.equal(applied.ok, true);
  assert.equal(applied.status, "APPLIED");
  assert.equal(applied.schema, "monitor.browser.tab-focus.receipt.v1");
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ["tab", 17, { active: true }],
    ["window", 33, { focused: true }],
  ]);

  const mismatchCalls = [];
  const mismatch = await loadAdapter().create({
    tabs: {
      get: async () => ({ id: 17, windowId: 44, url: tab.url, active: false }),
      update: async (...args) => mismatchCalls.push(args),
    },
    windows: {
      get: async () => ({ focused: false }),
      update: async (...args) => mismatchCalls.push(args),
    },
  }).focus(target);
  assert.equal(mismatch.status, "NOT_APPLIED");
  assert.equal(mismatch.error, "MONITOR_TAB_FOCUS_IDENTITY_MISMATCH");
  assert.deepEqual(mismatchCalls, []);

  const unknown = await loadAdapter().create({
    tabs: {
      get: async () => ({ id: 17, windowId: 33, url: tab.url, active: false }),
      update: async () => { throw new Error("transport failed"); },
    },
    windows: {
      get: async () => ({ focused: false }),
      update: async () => ({ focused: true }),
    },
  }).focus(target);
  assert.equal(unknown.status, "UNKNOWN");
  assert.equal(unknown.ok, false);

  const dotTarget = { tabId: 21, windowId: 34, dotKey: "b227a510-d0cb-4466-a2f5-4e401b456dca~6af1261141a8819aa57d94044451fee3" };
  const dotTab = { id: 21, windowId: 34, url: `https://chatgpt.com/dots/${dotTarget.dotKey}`, active: false };
  const dotCalls = [];
  const dotResult = await loadAdapter().create({
    tabs: {
      get: async () => ({ ...dotTab }),
      update: async (tabId, update) => { dotCalls.push(["tab", tabId, update]); dotTab.active = update.active === true; return { ...dotTab }; },
    },
    windows: {
      get: async () => ({ id: 34, focused: true }),
      update: async (windowId, update) => { dotCalls.push(["window", windowId, update]); return { id: windowId, focused: true }; },
    },
  }).focus(dotTarget);
  assert.equal(dotResult.status, "APPLIED");
  assert.deepEqual(JSON.parse(JSON.stringify(dotCalls)), [["tab", 21, { active: true }], ["window", 34, { focused: true }]]);
  const dotMismatch = await loadAdapter().create({
    tabs: { get: async () => ({ ...dotTab, url: "https://chatgpt.com/dots/other~reference" }), update: async () => { throw new Error("must not update"); } },
    windows: { get: async () => ({ id: 34, focused: false }), update: async () => { throw new Error("must not update"); } },
  }).focus(dotTarget);
  assert.equal(dotMismatch.status, "NOT_APPLIED");
  assert.equal(dotMismatch.error, "MONITOR_TAB_FOCUS_IDENTITY_MISMATCH");

  const background = fs.readFileSync(backgroundPath, "utf8");
  const monitor = fs.readFileSync(monitorPath, "utf8");
  assert.match(background, /importScripts\("browser\/tab-focus-adapter\.js"\)/);
  assert.match(background, /message\?\.type === "monitor-focus-exact-chat-tab"/);
  assert.match(monitor, /type: "monitor-focus-exact-chat-tab"/);
  assert.match(monitor, /tabId: node\.tabId/);
  assert.match(monitor, /windowId: node\.windowId/);
  assert.match(monitor, /conversationKey: node\.conversationKey/);
  assert.match(monitor, /dotKey: node\.dotKey/);

  console.log(JSON.stringify({
    status: "PASS",
    exact_identity_applied: true,
    mismatch_has_no_effect: true,
    ambiguous_effect_is_unknown: true,
    exact_dot_identity_applied: true,
    background_and_node_wiring: true,
  }));
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
