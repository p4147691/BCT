"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "extension", "monitor-bct-shell.js"),
  "utf8",
);
const monitorSource = fs.readFileSync(
  path.join(__dirname, "..", "extension", "monitor.js"),
  "utf8",
);
const desktopSource = fs.readFileSync(
  path.join(__dirname, "..", "extension", "desktop.html"),
  "utf8",
);
const manifest = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "extension", "manifest.json"),
  "utf8",
));
const opened = [];
const monitorState = {
  service: { status: "OK", ready: true, service: "bct-core" },
  rcc: {
    instances: [{
      instance_id: "rcc-live",
      session_id: "session-live",
      state: "OPEN",
      tabs: [
        { tab_id: 22, window_id: 12, title: "둘", url: "https://chatgpt.com/", presence: "OPEN", active: false, generating: true },
        { tab_id: 11, window_id: 10, title: "하나", url: "https://chatgpt.com/c/chat-one", node_label: "N7", presence: "OPEN", active: true, generating: false },
        { tab_id: 33, window_id: 12, title: "다른 사이트", url: "https://www.youtube.com/watch?v=test", presence: "OPEN", active: false, generating: false },
      ],
    }],
  },
};
const context = {
  globalThis: null,
  fetch: async (url, init) => {
    assert.equal(init?.cache, "no-store");
    if (url === "http://127.0.0.1:18790/monitor/conversation-title/rename") {
      assert.equal(init.method, "POST");
      assert.equal(init.headers["Content-Type"], "application/json");
      const body = JSON.parse(init.body);
      assert.deepEqual(body, {
        instance_id: "rcc-live",
        session_id: "session-live",
        tab_id: 11,
        conversation_key: "chat-one",
        title: "새 이름",
        operation_id: "monitor.rename.test-id",
        timeout_s: 30,
      });
      return {
        ok: true,
        status: 200,
        async json() {
          return { outcome: "APPLIED", output: { result: { savedTitle: "새 이름" } } };
        },
      };
    }
    if (url === "http://127.0.0.1:18790/monitor/state") {
      return { ok: true, status: 200, async json() { return monitorState; } };
    }
    assert.equal(url, "http://127.0.0.1:18790/health");
    return {
      ok: true,
      status: 200,
      async json() {
        return { status: "OK", ready: true, service: "bct-core", release_sha: "a".repeat(40), generation: 3, pid: 42 };
      },
    };
  },
  chrome: {
    windows: {
      async create(value) {
        opened.push(value);
        return { id: opened.length };
      },
    },
  },
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context);

(async () => {
  assert.equal(manifest.name, "BCT Window Monitor");
  assert.equal(manifest.version, "2.0.0");
  assert.ok(desktopSource.indexOf("monitor-bct-shell.js") < desktopSource.indexOf("monitor.js"));
  assert.match(monitorSource, /id="monitorBctOpen"/);
  assert.doesNotMatch(monitorSource, /id="monitorLocalLlmOpen"/);
  assert.match(monitorSource, /id="monitorRccRescan"/);
  assert.match(monitorSource, /id="monitorNodeCols3"/);
  assert.match(monitorSource, /id="monitorExtensionReload"/);
  assert.doesNotMatch(monitorSource, /id="monitorActRestart"/);
  assert.doesNotMatch(monitorSource, /id="monitorNodeSync"/);
  assert.match(monitorSource, /const MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED = false;/);
  assert.match(monitorSource, /const MONITOR_NODE_RENDER_ENABLED = false;/);
  assert.doesNotMatch(monitorSource, /monitor-ai-section" hidden/);
  assert.match(monitorSource, /id="monitorBctNodesRefresh"/);
  assert.match(monitorSource, /refreshMonitorBctWindowNodes/);
  assert.match(monitorSource, /addEventListener\("contextmenu"/);
  assert.match(monitorSource, /monitorBctShell\.renameConversation\(node, title\)/);
  assert.match(monitorSource, /event\.target === overlay/);
  assert.match(monitorSource, /event\.key === "Escape"/);
  assert.match(monitorSource, /dialog\.addEventListener\("submit"/);
  const shell = context.MonitorBctShell.create({ randomId: () => "test-id" });
  const health = await shell.health();
  assert.equal(health.service, "bct-core");
  assert.equal(health.generation, 3);
  const state = await shell.monitorState();
  const nodes = shell.windowNodes(state);
  assert.equal(nodes.length, 2);
  assert.deepEqual(
    Array.from(nodes, (node) => [node.windowId, node.tabId, node.presence, node.active, node.generating]),
    [[10, 11, "OPEN", true, false], [12, 22, "OPEN", false, true]],
  );
  assert.equal(nodes[0].conversationKey, "chat-one");
  assert.equal(nodes[0].nodeLabel, "N7");
  assert.equal(nodes[0].sessionId, "session-live");
  assert.equal(nodes[1].conversationKey, "");
  assert.equal(nodes[1].url, "https://chatgpt.com/");
  assert.ok(nodes.every((node) => /^https:\/\/(?:chatgpt\.com|chat\.openai\.com)(?:[/?#]|$)/i.test(node.url)));
  assert.throws(() => shell.windowNodes({ rcc: {} }), /BCT_RCC_STATE_INVALID/);
  const renamed = await shell.renameConversation(nodes[0], " 새 이름 ");
  assert.equal(renamed.operationId, "monitor.rename.test-id");
  await assert.rejects(shell.renameConversation(nodes[1], "이름"), /BCT_RENAME_EXACT_IDENTITY_REQUIRED/);
  await shell.openStatus();
  await shell.openLocalLlm();
  assert.deepEqual(
    opened.map((value) => value.url),
    ["http://127.0.0.1:18790/monitor", "http://127.0.0.1:18790/monitor#local-llm"],
  );
  assert.ok(opened.every((value) => value.type === "popup" && value.focused === true));
  console.log("PASS: BCT health, window-node summary, and explicit BCT/Laya boundaries");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
