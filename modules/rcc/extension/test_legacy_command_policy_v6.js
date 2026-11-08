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

const canonical = {
  'simple-relay-bind': 'rcc_bind_simple_relay',
  'simple-relay-send': 'rcc_send_simple_relay_message',
  'simple-relay-return': 'rcc_return_simple_relay_response',
  'new-chat-send': 'rcc_create_chat_and_send_message',
  'rename-conversation': 'rcc_rename_conversation',
  'conversation-bind': 'rcc_bind_conversation_to_node',
  'send-to-tab': 'rcc_send_message_to_tab',
  'send': 'rcc_send_message', 'presence': 'rcc_get_target_availability',
  'state': 'rcc_get_extension_state', 'result': 'rcc_get_operation_result',
  'probe-tabs': 'rcc_check_chat_tab_responses',
  'delivery-response-read': 'rcc_get_delivery_response',
  'create-chat-tab': 'rcc_create_chat_tab', 'create-chat-window': 'rcc_create_chat_window',
  'send-to-created-tab': 'rcc_send_message_to_created_tab',
  'move-tab': 'rcc_move_tab_to_window',
  'create-tab-group': 'rcc_create_tab_group_from_tabs',
  'add-tab-to-group': 'rcc_move_tab_to_group',
  'remove-tab-from-group': 'rcc_move_tab_from_group',
  'move-tab-group': 'rcc_move_tab_group_to_window',
  'update-tab-group': 'rcc_update_tab_group',
  'tab-get': 'rcc_get_tab', 'windows-list': 'rcc_list_windows',
  'window-get': 'rcc_get_window', 'tab-groups-list': 'rcc_list_tab_groups',
  'tab-group-get': 'rcc_get_tab_group',
  'read-latest-assistant': 'rcc_get_latest_assistant_message',
};
for (const command of Object.keys(canonical)) {
  assert.equal(policy.nativeCommand(command).allowed, true, command);
  assert.equal(policy.nativeCommand(`rcc_${command.replaceAll('-', '_')}`).allowed, true, `rcc_${command}`);
  assert.equal(policy.nativeCommand(canonical[command]).allowed, true, canonical[command]);
  assert.equal(policy.toNativeCommand(canonical[command]), command);
  assert.equal(policy.toNativeCommand(`rcc_${command.replaceAll('-', '_')}`), command);
  assert.equal(policy.toPublicNativeCommand(command), canonical[command]);
}
assert.deepEqual(policy.nativeCommand('send'), { allowed: true, kind: 'ORCHESTRATION' });
assert.deepEqual(policy.nativeCommand('send-to-tab'), { allowed: true, kind: 'EXACT_TAB' });
for (const command of ['create-chat-tab', 'create-chat-window', 'send-to-created-tab', 'move-tab', 'create-tab-group', 'add-tab-to-group', 'remove-tab-from-group', 'move-tab-group', 'update-tab-group']) {
  assert.deepEqual(policy.nativeCommand(command), { allowed: true, kind: 'ATOMIC_CHAT' }, command);
}
for (const command of ['register', 'send-wakeback', 'reload-workers', 'result-ack']) {
  assert.deepEqual(policy.nativeCommand(command), { allowed: false, kind: 'LEGACY_MUTATION' }, command);
}
for (const type of ['relay:activity', 'relay:getState', 'relay:getPendingStatus']) {
  assert.equal(policy.runtimeMessage(type).allowed, true, type);
}
for (const type of ['relay:orchestrationAuthorize', 'relay:orchestrationResult']) {
  assert.deepEqual(policy.runtimeMessage(type), { allowed: true, kind: 'ORCHESTRATION' }, type);
}
for (const type of ['relay:manualSend', 'relay:autoDirective', 'relay:workerResult', 'relay:actNaturalCommand']) {
  assert.deepEqual(policy.runtimeMessage(type), { allowed: false, kind: 'LEGACY_MUTATION' }, type);
}
assert.equal(policy.nativeCommand('unknown').allowed, false);
assert.equal(policy.runtimeMessage('relay:unknown').allowed, false);
assert(loader.includes("importScripts('legacy/command_policy.js');"));
const nativeHandler = nativeCommands.split('async function handleNativeCommand(message) {')[1];
assert(nativeHandler.includes('RccLegacyCommandPolicy.nativeCommand(wireCommand)'));
assert(nativeHandler.indexOf('RccLegacyCommandPolicy.nativeCommand(wireCommand)')
  < nativeHandler.indexOf("message.command === 'simple-relay-send'"));
for (const command of ['create-chat-tab', 'create-chat-window', 'send-to-created-tab', 'move-tab', 'create-tab-group', 'add-tab-to-group', 'remove-tab-from-group', 'move-tab-group', 'update-tab-group', 'tab-get', 'windows-list', 'window-get', 'tab-groups-list', 'tab-group-get', 'read-latest-assistant']) {
  assert(nativeHandler.includes(`message.command === '${command}'`), `${command} must have an active handler`);
}
for (const command of ['register', 'send-wakeback', 'reload-workers', 'result-ack']) {
  assert(!nativeHandler.includes(`message.command === '${command}'`), `${command} implementation must be pruned`);
}
assert(nativeHandler.includes("message.command === 'send'"));
const runtimeHandler = runtimeMessages.split('function handleRuntimeMessage(message, sender, sendResponse) {')[1];
assert(runtimeHandler.includes('RccLegacyCommandPolicy.runtimeMessage(message?.type)'));
assert(runtimeHandler.indexOf('RccLegacyCommandPolicy.runtimeMessage(message?.type)')
  < runtimeHandler.indexOf("message.type === 'relay:getPendingStatus'"));
for (const type of ['relay:manualSend', 'relay:autoDirective', 'relay:workerResult', 'relay:actNaturalCommand']) {
  assert(!runtimeHandler.includes(`message.type === '${type}'`), `${type} implementation must be pruned`);
}
for (const type of ['relay:simpleExecute', 'relay:simpleReadReply', 'relay:orchestrationExecute', 'relay:newChatExecute', 'relay:newChatStatus', 'relay:renameConversation', 'relay:activityProbe', 'relay:probe', 'relay:readLatestAssistant']) {
  assert(content.includes(`message.type === '${type}'`), `${type} active content route must remain`);
}
for (const type of ['relay:execute', 'relay:deliver', 'relay:bootstrap']) {
  assert(!content.includes(`message.type === '${type}'`), `${type} legacy content route must be pruned`);
}
assert.deepEqual(manifest.content_scripts[0].js, [
  'relay_core.js', 'content/conversation_dom.js', 'content/simple_relay_executor.js',
  'content/orchestration_relay_executor.js',
  'content/conversation_rename.js',
  'content/content_router.js', 'content/activity_reporter.js', 'content.js'
]);
assert(!loader.includes("importScripts('act_bridge.js');"));

console.log('legacy command policy v6: PASS');
