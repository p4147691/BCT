const assert = require('assert');
const fs = require('fs');
const path = require('path');
const extensionRoot = __dirname;
const identity = require(path.join(extensionRoot, 'core/identity.js'));
const state = require(path.join(extensionRoot, 'core/state.js'));
const conversation = require(path.join(extensionRoot, 'core/conversation.js'));
const transport = require(path.join(extensionRoot, 'core/transport.js'));
const relayCore = require(path.join(extensionRoot, 'relay_core.js'));
const simpleRelay = require(path.join(extensionRoot, 'simple_relay_v0.js'));

const manager = '6ad5afa4-b1e0-83ee-8692-aec4bb51523e';
const worker = '6ad4bb5d-6624-83ee-b045-e57fdad5120e';
const managerUrl = 'https://chatgpt.com/c/' + manager;
const workerUrl = 'https://chatgpt.com/c/' + worker;
const tabs = [{ id: 1, windowId: 10, url: managerUrl }, { id: 2, windowId: 20, url: workerUrl }];
const endpoints = [
  { tabId: 1, conversationKey: manager, presence: 'OPEN', generating: false },
  { tabId: 2, conversationKey: worker, presence: 'OPEN', generating: false },
];

assert.equal(identity.conversationKeyFromUrl(managerUrl), relayCore.conversationKey(managerUrl));
assert.equal(identity.conversationKeyFromUrl('https://chatgpt.com/c/local-chatgpt'), '');
assert.throws(() => identity.conversationUuid('not-a-uuid'), /RCC_CORE_CONVERSATION_UUID_INVALID/);
assert.equal(identity.resolveExactConversation(tabs, manager).status, 'EXACT');
assert.equal(identity.resolveExactConversation([], manager).status, 'MISSING');
assert.equal(identity.resolveExactConversation(tabs.concat([{ id: 3, url: managerUrl }]), manager).status, 'AMBIGUOUS');

assert.equal(state.inspectConversation(tabs, endpoints, manager).status, state.STATUS.CONNECTED);
assert.equal(state.inspectConversation(tabs, [{ ...endpoints[0], generating: true }, endpoints[1]], manager).status, state.STATUS.BUSY);
assert.equal(state.inspectConversation(tabs, [], manager).status, state.STATUS.RECEIVER_UNKNOWN);
assert.equal(state.inspectConversation(tabs, [{ ...endpoints[0], conversationKey: worker }, endpoints[1]], manager).status, state.STATUS.PROTOCOL_MISMATCH);
assert.equal(state.inspectPair(tabs, endpoints, manager, worker).connected, true);

const simpleRequest = simpleRelay.request({
  binding: simpleRelay.binding(manager, worker), from: 'manager', operationId: 'core-v1.1', text: '원문 보존',
});
const intent = conversation.submissionIntent({
  operationId: simpleRequest.operationId, targetConversationKey: simpleRequest.targetConversationKey, text: simpleRequest.text,
});
assert.deepEqual(intent, { operationId: 'core-v1.1', targetConversationKey: worker, text: '원문 보존' });
assert.equal(conversation.classifySubmissionAck({ ok: true, submitted: true, conversationKey: worker }, worker).state, 'SUBMITTED');
assert.equal(conversation.classifySubmissionAck({ submitted: false }, worker).state, 'NOT_APPLIED');
assert.equal(conversation.classifySubmissionAck({ ok: true, submitted: true, conversationKey: manager }, worker).state, 'UNKNOWN');
assert.equal(conversation.classifyReplyRead({
  conversationKey: worker, afterAssistantCount: 2, assistantCount: 3, responseText: '전문', generating: false,
}).state, 'REPLY_CAPTURED');
assert.equal(conversation.classifyReplyRead({
  conversationKey: worker, afterAssistantCount: 2, assistantCount: 3, responseText: '전문', generating: true,
}).state, 'NOT_APPLIED');

assert.deepEqual(transport.stateRequest({ instanceId: '6174664e1c1b4e6db1d4729c841db3c9', requestId: 'state.1' }), {
  instanceId: '6174664e1c1b4e6db1d4729c841db3c9', requestId: 'state.1', command: 'state',
});
assert.equal(transport.classifyDelivery({ intent, ack: { ok: true, submitted: true, conversationKey: worker } }).state, 'SUBMITTED');
assert.equal(transport.classifyDelivery({ intent, transportError: 'closed' }).state, 'UNKNOWN');
assert.equal(transport.mayAutomaticallyRetry('UNKNOWN'), false);
assert.equal(transport.mayAutomaticallyRetry('NOT_APPLIED'), false);
assert.equal(transport.requiresNewOperationForRetry('NOT_APPLIED'), true);
assert.equal(transport.requiresNewOperationForRetry('UNKNOWN'), false);

const manifest = fs.readFileSync(path.join(extensionRoot, 'manifest.json'), 'utf8');
const loader = fs.readFileSync(path.join(extensionRoot, 'background_loader.js'), 'utf8');
for (const coreFile of ['identity.js', 'state.js', 'conversation.js', 'transport.js']) {
  const text = fs.readFileSync(path.join(extensionRoot, 'core', coreFile), 'utf8');
  assert(!text.includes('chrome.'), coreFile + ' must remain pure source-only Core');
}
assert(!manifest.includes('core/'), 'Stage 1 must not add Core modules to the active manifest');
assert(!loader.includes('core/'), 'Stage 1 must not add Core modules to the active background loader');

console.log('rcc_core_v1 source-only tests: PASS');
