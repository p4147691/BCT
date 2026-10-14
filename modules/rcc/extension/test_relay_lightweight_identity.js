const assert = require('assert');
const fs = require('fs');

const content = fs.readFileSync('content.js', 'utf8');
const background = fs.readFileSync('background.js', 'utf8');

assert(content.includes("message.type === 'relay:activityProbe'"),
  'content script must expose a lightweight activity probe');

const activityBlock = content.split("message.type === 'relay:activityProbe'")[1].split("message.type === 'relay:probe'")[0];
assert(!activityBlock.includes('conversationTail('),
  'lightweight activity probe must not read conversation history');

assert(background.includes("{ type: 'relay:activityProbe' }"),
  'normal endpoint activity checks must use the lightweight probe');

assert(content.includes("relayRole === 'CONTROL' && markerScanEnabled"),
  'marker directive scanning must be explicitly gated');

assert(background.includes('markerScanEnabled: !!state.settings.armed'),
  'marker scanning must stay dormant unless auto-relay is armed');

assert(!content.includes("lastText: lastAssistantText().slice(-500)"),
  'diagnostic probe must not return assistant message text');

assert(content.includes('const relayGenerationRoot = conversationObserveRoot();') &&
       content.includes('relayGenerationObserver.observe(relayGenerationRoot'),
  'generation observer must be scoped to the conversation main');

assert(content.includes('relayAttentionObserver.observe(document.documentElement, { childList: true, subtree: true });'),
  'global observer must be limited to lightweight warning insertion/removal events');

const editorBlock = content.slice(content.indexOf('async function waitForEditor'), content.indexOf('function waitForNaverChatMode'));
assert(editorBlock.includes('new MutationObserver(check)') && !editorBlock.includes('while ('),
  'editor discovery must be event-driven, not polling');

const renameBlock = content.slice(content.indexOf('async function waitForRenameUi'), content.indexOf('function activateRenameUiElement'));
assert(renameBlock.includes('while (Date.now() < deadline)') && renameBlock.includes('await sleep(100)'),
  'rename UI discovery must remain bounded');


const submitBlock = content.slice(content.indexOf('function findReadySendButton'), content.indexOf('async function waitForReply'));
assert(submitBlock.includes('new MutationObserver(check)') && !submitBlock.includes('await sleep(250)'),
  'send readiness must be event-driven, not fixed-delay polling');

const naverBlock = content.slice(content.indexOf('function waitForNaverChatMode'), content.indexOf('function waitForRelaySubmissionAccepted'));
assert(naverBlock.includes('waitForNaverChatMode') &&
       naverBlock.includes('new MutationObserver(check)') &&
       !naverBlock.includes('while (Date.now() < modeDeadline)') &&
       !naverBlock.includes('await sleep(500)'),
  'NAVER bootstrap must use event-driven mode/editor/conversation identity waits');


const actContent = fs.readFileSync('act_content.js', 'utf8');
assert(!actContent.includes('rcc-bootstrap-role-command-v1') &&
       !actContent.includes('chrome.runtime.reload()'),
  'ACT content must not auto-reload the RCC extension');

assert(background.includes("message.command === 'reload-extension'") &&
       background.includes('chrome.runtime.reload()'),
  'explicit user-requested extension reload must remain available');


assert(content.includes("const RCC_BUILD_VERSION = '2026-10-14-rcc-orchestration-recovery-v4';"),

  'content script must expose an internal RCC build version');

const probeBlock = content.split("message.type === 'relay:probe'")[1];
assert(probeBlock.includes('buildVersion: RCC_BUILD_VERSION'),
  'relay probe must report the internal RCC build version');


const activityVersionBlock = content.split("message.type === 'relay:activityProbe'")[1].split("message.type === 'relay:probe'")[0];
assert(activityVersionBlock.includes('buildVersion:RCC_BUILD_VERSION'),
  'lightweight activity telemetry must report the internal RCC build version');


assert(background.includes("message.command === 'probe-tabs'"),
  'background must expose a role-free read-only tab probe');

const probeTabsBlock = background.slice(
  background.indexOf("message.command === 'probe-tabs'"),
  background.indexOf("message.command === 'diagnose-activity'")
);
assert(probeTabsBlock.includes("chrome.tabs.sendMessage(tab.id, { type: 'relay:probe' })") &&
       !probeTabsBlock.includes('sendToChatTab(') &&
       !probeTabsBlock.includes('executeScript') &&
       !probeTabsBlock.includes('reload(') &&
       !probeTabsBlock.includes('storage.local.set'),
  'probe-tabs must be read-only and must not inject, reload, or mutate tab/registration state');

console.log('relay lightweight/event-driven tests: PASS (19/19)');
