"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "domains", "shared-ui.js"), "utf8");
const start = source.indexOf("function scheduleMonitorChatNavigationRefresh(");
const endMarker = "//@@FN_END:scheduleMonitorChatNavigationRefresh";
const end = source.indexOf(endMarker, start);
assert.ok(start >= 0 && end > start, "chat navigation refresh function must be extractable");

(async () => {
  const timers = [];
  const applied = [];
  let releaseOldRefresh;
  const oldRefresh = new Promise((resolve) => { releaseOldRefresh = resolve; });
  let refreshCount = 0;
  const context = {
    monitorChatNavigationRefreshTimer: 0,
    monitorChatNavigationPendingByTab: new Map(),
    monitorChatNavigationRefreshGeneration: 0,
    monitorLastAiState: {},
    monitorBrowserRosterRefreshPending: false,
    applyMonitorChatNavigationIdentity(message) { applied.push(Number(message.tabId)); return { ok: true }; },
    refreshMonitorEndpointRegistry: async () => {
      refreshCount += 1;
      if (refreshCount === 1) await oldRefresh;
    },
    refreshMonitorBctWindowNodes: async () => {},
    refreshMonitorConversationStateFast: async () => {},
    refreshMonitorIdentityIndex: async () => {},
    refreshMonitorBctCurrentSessionWindowHwnd() {},
    refreshMonitorBctDisplayWindowHwnd() {},
    syncMonitorAllDesktopThumbnailNodeBadges() {},
    console: { warn() {} },
    setTimeout(callback) { timers.push(callback); return timers.length; },
    clearTimeout() {},
    Number, Math, Map, Array, String,
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end), context);

  context.scheduleMonitorChatNavigationRefresh({ tabId: 101, active: true, at: 100 });
  const oldRun = timers.shift()();
  await Promise.resolve();
  context.scheduleMonitorChatNavigationRefresh({ tabId: 202, active: true, at: 200 });
  releaseOldRefresh();
  await oldRun;
  await timers.shift()();

  assert.deepEqual(applied.slice(0, 2), [101, 202], "real tab activation selects immediately");
  assert.equal(applied.slice(2).every((tabId) => tabId === 202), true,
    "an older asynchronous refresh must not reselect its stale tab");
  console.log(JSON.stringify({ status: "PASS", stale_refresh_cannot_override_new_tab: true }));
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
