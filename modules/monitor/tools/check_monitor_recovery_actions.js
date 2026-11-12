"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const nativeSource = fs.readFileSync(path.join(root, "native", "src", "MonitorDesktopHost.cs"), "utf8");
const background = fs.readFileSync(path.join(root, "extension", "background.js"), "utf8");
const bctToolRefresh = fs.readFileSync(
  path.join(root, "extension", "browser", "bct-control-tool-refresh-adapter.js"), "utf8");
const tabClose = fs.readFileSync(path.join(root, "extension", "browser", "tab-close-adapter.js"), "utf8");
const monitor = fs.readFileSync(path.join(root, "extension", "monitor.js"), "utf8");

assert.match(nativeSource, /recoverBctCore/);
assert.match(nativeSource, /recoverMcpTunnel/);
assert.match(nativeSource, /BCT Core Supervisor/);
assert.match(nativeSource, /BCT Tunnel Supervisor/);
assert.match(nativeSource, /Path\.Combine\(Environment\.SystemDirectory, "schtasks\.exe"\)/);
assert.match(nativeSource, /BCT_CORE_RECOVERY_NOT_READY/);
assert.match(nativeSource, /BCT_TUNNEL_RECOVERY_NOT_READY/);
assert.match(nativeSource, /127\.0\.0\.1/);
assert.doesNotMatch(nativeSource, /cmd\.exe/);

assert.match(background, /monitor-refresh-bct-control-tools/);
assert.match(background, /MonitorBctControlToolRefreshAdapter\.create\(chrome\)/);
assert.match(background, /monitorBctControlToolRefreshAdapter\.refreshTools\(\)/);
assert.match(bctToolRefresh, /asdk_app_6ac3a06ea58c819195b90feb131b6da5/);
assert.match(bctToolRefresh, /monitor\.bct-control\.tool-refresh\.receipt\.v1/);
assert.match(bctToolRefresh, /BCT_CONTROL_REFRESH_COMPLETION_UNVERIFIED/);
assert.match(bctToolRefresh, /status:"UNKNOWN"/);
assert.match(background, /monitor-close-chat-tab/);
assert.match(background, /MonitorTabCloseAdapter\.create\(chrome\)/);
assert.match(background, /monitorTabCloseAdapter\.close\(message\)/);
assert.match(tabClose, /monitor\.browser\.tab-close\.receipt\.v1/);
assert.match(tabClose, /MONITOR_TAB_CLOSE_IDENTITY_MISMATCH/);
assert.match(tabClose, /await chromeApi\.tabs\.remove\(target\.tabId\)/);
assert.match(tabClose, /receipt\("CLOSED", target, \{ verified: true, closed: true \}\)/);

assert.match(monitor, /monitorBctShell\.reloadRcc\(instanceId\)/);
assert.match(monitor, /BCT 도구 새로고침 완료/);
assert.match(monitor, /다시 누르지 말고 플러그인 설정을 확인하세요/);
assert.match(monitor, /RCC_RELOAD_EXACT_INSTANCE_REQUIRED/);
assert.match(monitor, /RCC 리로드 요청 수락/);
assert.match(monitor, /RCC 리로드 완료 · 새 연결 확인됨/);
assert.match(monitor, /새 연결은 아직 미확인/);
assert.match(monitor, /beforeSessions/);
assert.match(monitor, /restoreMonitorTrashedConversation/);
assert.match(
  monitor,
  /renderMonitorClosedConversationRecoveryPanel\(monitorLastAiState\|\|\{\}\)/,
  "the recovery bin must render its empty sections before the first AI state snapshot",
);
assert.doesNotMatch(
  monitor,
  /monitorClosedConversationPickerOpen&&monitorClosedRecoveryMenu&&monitorLastAiState/,
  "an absent AI state snapshot must not suppress an already-open recovery bin",
);
assert.match(monitor, /monitorBctShell\.retireConversationNode/);
assert.match(monitor, /type:"monitor-close-chat-tab"/);
assert.doesNotMatch(monitor, /ORCHESTRATOR_CONVERSATION_CLOSE_TAB_URL,\{method:"POST"/);

console.log("PASS: bounded BWM recovery actions and exact BCT Control tool refresh contracts");
