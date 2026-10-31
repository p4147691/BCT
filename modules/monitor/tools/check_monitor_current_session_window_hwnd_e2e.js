"use strict";

// Read-only live acceptance probe. It never sends a relay, changes a Chrome
// window, reloads an extension, or writes BCT state. It proves only the
// current-session identity join needed before the separate live thumbnail E2E.
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const hostPath = process.env.MONITOR_NATIVE_HOST || "D:\\ChromeExtensions\\DesktopWindow-Monitor\\native\\1.9.20.173-dwm-ui\\DesktopWindowMonitorHost.exe";

function loadModule(file, exported) {
  const context = { globalThis: null, Map, Set, Object, String, Number, Array, Date };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(file, "utf8"), context);
  return context[exported];
}

function createNativeClient() {
  const host = spawn(hostPath, [], { stdio: ["pipe", "pipe", "inherit"] });
  let received = Buffer.alloc(0);
  const waiters = [];
  host.stdout.on("data", (chunk) => {
    received = Buffer.concat([received, chunk]);
    while (received.length >= 4) {
      const length = received.readUInt32LE(0);
      if (received.length < length + 4) return;
      const payload = JSON.parse(received.subarray(4, length + 4).toString("utf8"));
      received = received.subarray(length + 4);
      waiters.shift()?.resolve(payload);
    }
  });
  host.on("error", (error) => waiters.splice(0).forEach((waiter) => waiter.reject(error)));
  return {
    request(message) {
      return new Promise((resolve, reject) => {
        const body = Buffer.from(JSON.stringify(message), "utf8");
        const header = Buffer.alloc(4); header.writeUInt32LE(body.length, 0);
        waiters.push({ resolve, reject }); host.stdin.write(Buffer.concat([header, body]));
      });
    },
    close() { host.kill(); },
  };
}

(async () => {
  const BctShell = loadModule(path.join(root, "extension", "monitor-bct-shell.js"), "MonitorBctShell");
  const HwndContract = loadModule(path.join(root, "extension", "monitor-window-hwnd-contract.js"), "MonitorWindowHwndContract");
  const stateResponse = await fetch("http://127.0.0.1:18790/monitor/state", { cache: "no-store" });
  assert.equal(stateResponse.ok, true, `BCT_MONITOR_HTTP_${stateResponse.status}`);
  const state = await stateResponse.json();
  const shell = BctShell.create();
  const nodes = shell.windowNodes(state);
  const native = createNativeClient();
  try {
    const desktops = await native.request({ type: "getVirtualDesktops" });
    assert.equal(desktops.ok, true, desktops.error || "getVirtualDesktops failed");
    const locations = new Map();
    for (const desktopId of Array.isArray(desktops.desktopIds) ? desktops.desktopIds : []) {
      const snapshot = await native.request({ type: "getDesktopWindowHandles", desktopId, includeMonitorWindows: true });
      assert.equal(snapshot.ok, true, snapshot.error || "getDesktopWindowHandles failed");
      for (const item of Array.isArray(snapshot.windows) ? snapshot.windows : []) {
        if (String(item?.className || "") !== "Chrome_WidgetWin_1") continue;
        const hwnd = String(item?.hwnd || "").trim();
        if (!/^\d+$/.test(hwnd) || hwnd === "0") continue;
        const identity = await native.request({ type: "getChromeConversationIdentity", hwnd });
        locations.set(hwnd, {
          hwnd, conversationKey: String(identity?.conversationKey || ""), identityAt: Date.now(),
          iconic: item?.iconic === true, desktopId: String(desktopId || ""),
        });
      }
    }
    const resolution = HwndContract.create().resolve({ nodes, locations, now: Date.now() });
    const mappedHwnds = new Set(resolution.bindings.map((binding) => binding.hwnd));
    const minimizedMapped = [...locations.values()].filter((location) => mappedHwnds.has(location.hwnd) && location.iconic).length;
    const minimizedNodes = resolution.bindings
      .filter((binding) => locations.get(binding.hwnd)?.iconic === true)
      .map((binding) => {
        const node = nodes.find((candidate) =>
          String(candidate?.instanceId || "") === String(binding.instanceId || "") &&
          String(candidate?.sessionId || "") === String(binding.sessionId || "") &&
          String(candidate?.windowId || "") === String(binding.windowId || ""));
        const location = locations.get(binding.hwnd) || {};
        const desktopId = String(location.desktopId || "");
        return {
          hwnd: binding.hwnd, nodeLabel: String(node?.nodeLabel || "N?"), tabId: Number(node?.tabId || 0),
          desktopId, desktopNumber: desktops.desktopIds.indexOf(desktopId) + 1,
        };
      });
    console.log(JSON.stringify({
      ok: true, schema: resolution.schema, chatgpt_tabs: nodes.length,
      active_chatgpt_windows: nodes.filter((node) => node.active && node.conversationKey).length,
      native_chrome_windows: locations.size, mapped_windows: resolution.bindings.length,
      rejected: resolution.rejected.length, mapped_minimized_windows: minimizedMapped, minimized_nodes: minimizedNodes,
      live_thumbnail_transition: "NOT_RUN_SOURCE_NOT_APPLIED",
    }));
  } finally { native.close(); }
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
