const assert = require('assert');
const relay = require('./relay/contract.js');

const manager = '6ad5afa4-b1e0-83ee-8692-aec4bb51523e';
const worker = '6ad4bb5d-6624-83ee-b045-e57fdad5120e';
const binding = relay.binding(manager.toUpperCase(), worker);

assert.deepStrictEqual(binding, {
  version: 0, managerConversationKey: manager, workerConversationKey: worker,
});
assert.deepStrictEqual(relay.targetFor(binding, 'MANAGER'), {
  from: 'manager', to: 'worker', sourceConversationKey: manager, targetConversationKey: worker,
});
assert.deepStrictEqual(relay.targetFor(binding, 'worker'), {
  from: 'worker', to: 'manager', sourceConversationKey: worker, targetConversationKey: manager,
});
assert.throws(() => relay.binding(manager, manager), /SIMPLE_RELAY_ENDPOINTS_MUST_DIFFER/);
assert.throws(() => relay.request({ binding, from: 'manager', operationId: 'x', text: '' }), /SIMPLE_RELAY_TEXT_INVALID/);
assert.throws(() => relay.request({ binding, from: 'other', operationId: 'x', text: 'x' }), /SIMPLE_RELAY_ROLE_INVALID/);
assert.throws(() => relay.request({ binding, from: 'manager', operationId: 'bad id', text: 'x' }), /SIMPLE_RELAY_OPERATION_ID_INVALID/);
console.log('simple_relay_v0: PASS');
