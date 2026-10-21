const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = __dirname;
const policy = require(path.join(root, 'legacy/command_policy.js'));
const loader = fs.readFileSync(path.join(root, 'background_loader.js'), 'utf8');
const nativeCommands = fs.readFileSync(path.join(root, 'domain/readonly_diagnostics.js'), 'utf8');
const runtimeMessages = fs.readFileSync(path.join(root, 'domain/runtime_message_service.js'), 'utf8');
const content = fs.readFileSync(path.join(root, 'content/content_router.js'), 'utf8');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));

for (const command of ['simple-relay-bind', 'simple-relay-send', 'simple-relay-return', 'new-chat-send', 'rename-conversation', 'conversation-bind', 'state', 'result', 'probe-tabs']) {
  assert.equal(policy.nativeCommand(command).allowed, true, command);
}
for (const command of ['create-chat-tab', 'move-tab', 'register', 'send', 'send-wakeback', 'reload-workers', 'result-ack']) {
  assert.deepEqual(policy.nativeCommand(command), { allowed: false, kind: 'LEGACY_MUTATION' }, command);
}
for (const type of ['relay:activity', 'relay:getState', 'relay:getPendingStatus']) {
  assert.equal(policy.runtimeMessage(type).allowed, true, type);
}
for (const type of ['relay:manualSend', 'relay:autoDirective', 'relay:workerResult', 'relay:actNaturalCommand']) {
  assert.deepEqual(policy.runtimeMessage(type), { allowed: false, kind: 'LEGACY_MUTATION' }, type);
}
assert.equal(policy.nativeCommand('unknown').allowed, false);
assert.equal(policy.runtimeMessage('relay:unknown').allowed, false);
assert(loader.includes("importScripts('legacy/command_policy.js');"));
const nativeHandler = nativeCommands.split('async function handleNativeCommand(message) {')[1];
assert(nativeHandler.includes('RccLegacyCommandPolicy.nativeCommand(message.command)'));
assert(nativeHandler.indexOf('RccLegacyCommandPolicy.nativeCommand(message.command)')
  < nativeHandler.indexOf("message.command === 'simple-relay-send'"));
for (const command of ['create-chat-tab', 'move-tab', 'register', 'send', 'send-wakeback', 'reload-workers', 'result-ack']) {
  assert(!nativeHandler.includes(`message.command === '${command}'`), `${command} implementation must be pruned`);
}
const runtimeHandler = runtimeMessages.split('function handleRuntimeMessage(message, sender, sendResponse) {')[1];
assert(runtimeHandler.includes('RccLegacyCommandPolicy.runtimeMessage(message?.type)'));
assert(runtimeHandler.indexOf('RccLegacyCommandPolicy.runtimeMessage(message?.type)')
  < runtimeHandler.indexOf("message.type === 'relay:getPendingStatus'"));
for (const type of ['relay:manualSend', 'relay:autoDirective', 'relay:workerResult', 'relay:actNaturalCommand']) {
  assert(!runtimeHandler.includes(`message.type === '${type}'`), `${type} implementation must be pruned`);
}
for (const type of ['relay:simpleExecute', 'relay:simpleReadReply', 'relay:newChatExecute', 'relay:newChatStatus', 'relay:renameConversation', 'relay:activityProbe', 'relay:probe']) {
  assert(content.includes(`message.type === '${type}'`), `${type} active content route must remain`);
}
for (const type of ['relay:execute', 'relay:deliver', 'relay:bootstrap']) {
  assert(!content.includes(`message.type === '${type}'`), `${type} legacy content route must be pruned`);
}
assert.deepEqual(manifest.content_scripts[0].js, [
  'relay_core.js', 'content/conversation_dom.js', 'content/simple_relay_executor.js',
  'content/conversation_rename.js',
  'content/content_router.js', 'content/activity_reporter.js', 'content.js'
]);
assert(!loader.includes("importScripts('act_bridge.js');"));

console.log('legacy command policy v6: PASS');
