const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = __dirname;
const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8');
const loader = read('background_loader.js');
const manifest = JSON.parse(read('manifest.json'));
const background = read('background.js');
const content = read('content.js');

const domainFiles = [
  'domain/state_service.js',
  'domain/simple_relay_receipts.js',
  'domain/endpoint_service.js',
  'domain/diagnostic_support.js',
  'domain/simple_relay_service.js',
  'domain/new_chat_service.js',
  'domain/conversation_rename_service.js',
  'domain/readonly_diagnostics.js',
  'domain/runtime_message_service.js',
];
const contentFiles = [
  'content/conversation_dom.js',
  'content/simple_relay_executor.js',
  'content/conversation_rename.js',
  'content/content_router.js',
  'content/activity_reporter.js',
];

for (const relative of ['boot/platform_context.js', ...domainFiles, 'boot/background_app.js']) {
  assert(loader.includes(`importScripts('${relative}');`), `${relative} must be active`);
  assert(loader.indexOf(`importScripts('${relative}');`) < loader.indexOf("importScripts('background.js');"));
}
assert.deepEqual(manifest.content_scripts[0].js, [
  'relay_core.js', ...contentFiles, 'content.js',
]);

assert(background.split(/\r?\n/).length <= 600, 'background entrypoint must remain below 600 lines');
assert(content.split(/\r?\n/).length <= 600, 'content entrypoint must remain below 600 lines');
assert(background.includes('RccBackgroundApp.start()'));
assert(!background.includes('chrome.'));

const endpoint = read('domain/endpoint_service.js');
const receipts = read('domain/simple_relay_receipts.js');
const relay = read('domain/simple_relay_service.js');
const newChat = read('domain/new_chat_service.js');
const rename = read('domain/conversation_rename_service.js');
const diagnostics = read('domain/readonly_diagnostics.js');
const runtime = read('domain/runtime_message_service.js');
assert(endpoint.includes('async function captureEndpointSnapshot('));
assert(endpoint.includes('async function ensureRelayReceivers('));
assert(receipts.includes('async function writeSimpleRelayV0Receipt('));
assert(receipts.includes('function publicSimpleRelayV0Receipt('));
assert(relay.includes('async function bindSimpleRelayV0('));
assert(relay.includes('async function sendSimpleRelayV0('));
assert(relay.includes('async function returnSimpleRelayV0('));
assert(newChat.includes('async function sendNewChatAndAwaitResult('));
assert(rename.includes('async function runConversationRename('));
assert(rename.includes("type: 'relay:renameConversation'"));
assert(diagnostics.includes("message.command === 'diagnose-conversation-ui'"));
assert(runtime.includes("message.type === 'relay:getPendingStatus'"));
assert(runtime.includes('lifecycle.runtimeSenderKind(sender)'));
assert(runtime.includes('RCC_RUNTIME_SENDER_REJECTED'));
for (const relative of domainFiles) {
  assert(!read(relative).includes('chrome.'), `${relative} must use platform services`);
}

const dom = read('content/conversation_dom.js');
const executor = read('content/simple_relay_executor.js');
const conversationRename = read('content/conversation_rename.js');
const router = read('content/content_router.js');
const activity = read('content/activity_reporter.js');
assert(dom.includes('function resolveRoutedTurn('));
assert(executor.includes('async function executeSimpleRelayV0('));
assert(executor.includes('async function readSimpleRelayV0Reply('));
assert(executor.includes('async function executeNewChatBootstrap('));
assert(executor.includes('async function readNewChatBootstrapStatus('));
assert(executor.includes('const isNewChatBootstrap = tracking?.bootstrapCreatedTab === true;'));
assert(executor.includes('allowKeyboardFallback: !isNewChatBootstrap'));
assert(conversationRename.includes('async function renameConversationUi('));
assert(router.includes("message.type === 'relay:simpleExecute'"));
assert(router.includes("message.type === 'relay:simpleReadReply'"));
assert(router.includes("message.type === 'relay:newChatExecute'"));
assert(router.includes("message.type === 'relay:newChatStatus'"));
assert(router.includes("message.type === 'relay:renameConversation'"));
assert(router.includes('RCC_CONTENT_SENDER_REJECTED'));
assert(activity.includes('async function reportGenerationSignal('));

const active = [
  ...[...loader.matchAll(/importScripts\('([^']+)'\)/g)].map((match) => match[1]),
  ...manifest.content_scripts[0].js,
].map(read).join('\n');
const names = [...active.matchAll(/(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/g)]
  .map((match) => match[1]);
for (const name of new Set(names)) {
  const count = (active.match(new RegExp(`\\b${name}\\b`, 'g')) || []).length;
  assert(count > 1, `active named function has no caller: ${name}`);
}
const topLevelNames = [...active.matchAll(/^(?:const|let)\s+([A-Za-z_$][\w$]*)/gm)]
  .map((match) => match[1]);
for (const name of new Set(topLevelNames)) {
  const count = (active.match(new RegExp(`\\b${name}\\b`, 'g')) || []).length;
  assert(count > 1, `active top-level variable has no caller: ${name}`);
}

console.log('rcc domain/content boundaries v3: PASS');
