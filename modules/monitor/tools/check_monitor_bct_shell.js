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
        { tab_id: 11, window_id: 10, title: "하나", url: "https://chatgpt.com/c/chat-one", node_label: "N7", presence: "OPEN", active: true, generating: false,
          conversation_scope: { scope_id: "network.monitor", scope_name: "모니터 관리", role_tags: ["Manager", "검토"] } },
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
    if (url === "http://127.0.0.1:18790/monitor/rcc/reload") {
      assert.equal(init.method, "POST");
      assert.deepEqual(JSON.parse(init.body), {
        instance_id: "rcc-live",
        operation_id: "monitor.rcc-reload.test-id",
        timeout_s: 10,
      });
      return {
        ok: true,
        status: 200,
        async json() { return { outcome: "APPLIED", evidence: { command: "reload-extension" } }; },
      };
    }
    if (url === "http://127.0.0.1:18790/monitor/conversation-network/update") {
      assert.equal(init.method, "POST");
      assert.deepEqual(JSON.parse(init.body), {
        conversation_key: "chat-one",
        display_name: "새 이름",
        scope_name: "모니터 관리",
        role_tags: ["Manager", "검토"],
      });
      return {
        ok: true,
        status: 200,
        async json() {
          return { status: "OK", conversation: { scope_name: "모니터 관리", role_tags: ["Manager", "검토"] } };
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
  assert.match(monitorSource, /id="monitorTitle">BWM</);
  assert.doesNotMatch(monitorSource, /id="monitorBctOpen"/);
  assert.doesNotMatch(monitorSource, /id="monitorBctStatus"/);
  assert.doesNotMatch(monitorSource, /id="monitorLocalLlmOpen"/);
  assert.doesNotMatch(monitorSource, /id="monitorRccRescan"/);
  assert.doesNotMatch(monitorSource, /id="monitorNodeCols[23]"/);
  assert.match(monitorSource, /id="monitorExtensionReload"/);
  assert.match(monitorSource, /id="monitorRccReload"/);
  assert.match(monitorSource, /id="monitorBctRecover"/);
  assert.match(monitorSource, /id="monitorMcpTunnelRecover"/);
  assert.match(monitorSource, /id="monitorBctControlRefresh"/);
  assert.doesNotMatch(monitorSource, /id="monitorRccReload" type="button" disabled/);
  assert.doesNotMatch(monitorSource, /id="monitorBctRecover" type="button" disabled/);
  assert.doesNotMatch(monitorSource, /id="monitorMcpTunnelRecover" type="button" disabled/);
  assert.doesNotMatch(monitorSource, /id="monitorBctControlRefresh" type="button" disabled/);
  assert.match(monitorSource, />BC 도구 새로고침<\/button>/);
  assert.match(monitorSource, /type:"recoverBctCore"/);
  assert.match(monitorSource, /type:"recoverMcpTunnel"/);
  assert.match(monitorSource, /type:"monitor-refresh-exact-chatgpt-tab"/);
  assert.match(monitorSource, /monitorWorkers\.dataset\.columns = "3"/);
  assert.match(monitorSource, /monitorVersion\.classList\.add\("healthy"\)/);
  assert.doesNotMatch(monitorSource, /id="monitorActRestart"/);
  assert.doesNotMatch(monitorSource, /id="monitorNodeSync"/);
  assert.match(monitorSource, /const MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED = false;/);
  assert.match(monitorSource, /const MONITOR_NODE_RENDER_ENABLED = false;/);
  assert.doesNotMatch(monitorSource, /monitor-ai-section" hidden/);
  assert.match(monitorSource, /id="monitorBctNodesRefresh"/);
  assert.match(monitorSource, /refreshMonitorBctWindowNodes/);
  assert.match(monitorSource, /addEventListener\("contextmenu"/);
  assert.match(monitorSource, /monitorBctShell\.renameConversation\(node, title\)/);
  assert.match(monitorSource, /monitorBctShell\.updateConversationScope\(node,/);
  assert.match(monitorSource, /Manager는 안내용 역할 태그입니다/);
  assert.match(monitorSource, /setTimeout\(\(\) => \{[\s\S]*?\}, 600\)/);
  assert.match(monitorSource, /network_name:String\(bctNode\?\.scopeName/);
  assert.match(monitorSource, /openMonitorTrashRecovery/);
  assert.doesNotMatch(monitorSource, /첫 노드[\s\S]{0,120}Manager/);
  assert.doesNotMatch(monitorSource, /Manager[\s\S]{0,120}후임/);
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
  assert.equal(nodes[0].scopeName, "모니터 관리");
  assert.deepEqual(Array.from(nodes[0].roleTags), ["Manager", "검토"]);
  assert.equal(nodes[1].conversationKey, "");
  assert.equal(nodes[1].url, "https://chatgpt.com/");
  assert.ok(nodes.every((node) => /^https:\/\/(?:chatgpt\.com|chat\.openai\.com)(?:[/?#]|$)/i.test(node.url)));
  const tabOrdered = shell.windowNodes({
    rcc: { instances: [{
      instance_id: "rcc-live", session_id: "session-live", state: "OPEN",
      tabs: [
        { tab_id: 7, window_id: 20, tab_index: 5, title: "N7", url: "https://chatgpt.com/c/seven", node_label: "N7" },
        { tab_id: 4, window_id: 20, tab_index: 1, title: "N4", url: "https://chatgpt.com/c/four", node_label: "N4" },
        { tab_id: 9, window_id: 20, tab_index: 3, title: "N9", url: "https://chatgpt.com/c/nine", node_label: "N9" },
      ],
    }] },
  });
  assert.deepEqual(Array.from(tabOrdered, (node) => node.nodeLabel), ["N4", "N9", "N7"],
    "window nodes must follow the current Chrome tab strip order");
  const tabReordered = shell.windowNodes({
    rcc: { instances: [{
      instance_id: "rcc-live", session_id: "session-live", state: "OPEN",
      tabs: [
        { tab_id: 7, window_id: 20, tab_index: 3, title: "N7", url: "https://chatgpt.com/c/seven", node_label: "N7" },
        { tab_id: 4, window_id: 20, tab_index: 1, title: "N4", url: "https://chatgpt.com/c/four", node_label: "N4" },
        { tab_id: 9, window_id: 20, tab_index: 5, title: "N9", url: "https://chatgpt.com/c/nine", node_label: "N9" },
      ],
    }] },
  });
  assert.deepEqual(Array.from(tabReordered, (node) => node.nodeLabel), ["N4", "N7", "N9"],
    "moving a Chrome tab must change the grouped node order on the next snapshot");
  const retainedDisplay = shell.displayWindowNodes({
    service: monitorState.service,
    rcc: { instances: [{ instance_id: "rcc-live", state: "UNAVAILABLE", tabs: [] }] },
  }, nodes);
  assert.equal(retainedDisplay.length, 2);
  assert.ok(retainedDisplay.every((node) => node.displayStale === true && node.instanceCached === true));
  assert.ok(retainedDisplay.every((node) => node.instanceState === "UNAVAILABLE" && node.lastKnownState === "OPEN"));
  assert.throws(() => shell.windowNodes({ rcc: {} }), /BCT_RCC_STATE_INVALID/);
  const renamed = await shell.renameConversation(nodes[0], " 새 이름 ");
  assert.equal(renamed.operationId, "monitor.rename.test-id");
  const reloaded = await shell.reloadRcc("rcc-live");
  assert.equal(reloaded.operationId, "monitor.rcc-reload.test-id");
  assert.equal(reloaded.instanceId, "rcc-live");
  const scoped = await shell.updateConversationScope(nodes[0], {
    displayName: "새 이름",
    scopeName: "모니터 관리",
    roleTags: ["Manager", "검토"],
  });
  assert.equal(scoped.scope_name, "모니터 관리");
  await assert.rejects(shell.reloadRcc("x"), /BCT_RCC_RELOAD_EXACT_INSTANCE_REQUIRED/);
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
