const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { TextEncoder } = require('util');
const { webcrypto } = require('crypto');

const storage = {};
const sends = [];
const context = {
  console, TextEncoder, crypto: webcrypto,
  RelayCore: {
    conversationKey(url) { return String(url).split('/c/')[1] || ''; },
  },
  stateRepository: {
    async getLocal(key) { return { [key]: storage[key] }; },
    async setLocal(value) { Object.assign(storage, value); },
  },
  async getChatTabs() {
    return [
      { id: 10, windowId: 100,
        url: 'https://chatgpt.com/c/11111111-1111-1111-1111-111111111111' },
      { id: 20, windowId: 200,
        url: 'https://chatgpt.com/c/22222222-2222-2222-2222-222222222222' },
    ];
  },
  async sendToChatTab(tabId, message) {
    sends.push({ tabId, message });
    if (message.type === 'relay:simpleReadReply') {
      return { ok: true, conversationKey: message.conversationKey,
        responseText: tabId === 10 ? 'manager next' : 'worker reply' };
    }
    return { ok: true, submitted: true, conversationKey: message.conversationKey,
      beforeAssistantCount: 3 };
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname + '/domain/simple_relay_receipts.js', 'utf8'), context);
vm.runInContext(fs.readFileSync(__dirname + '/domain/delivery_ledger_service.js', 'utf8'), context);

(async () => {
  const text = 'one exact message';
  const requestSha256 = await context.relaySha256(text);
  const identity = {
    deliveryId: 'delivery-001', text, requestSha256,
    managerConversationKey: '11111111-1111-1111-1111-111111111111',
    workerConversationKey: '22222222-2222-2222-2222-222222222222',
  };
  const started = await context.deliveryStart(identity);
  assert.equal(started.state, 'SENT_WAITING');
  const replay = await context.deliveryStart(identity);
  assert.equal(replay.replayed, true);
  assert.equal(sends.length, 1);
  const captured = await context.deliveryStatus({ deliveryId: 'delivery-001' });
  assert.equal(captured.state, 'REPLY_CAPTURED');
  assert.equal(captured.responseLength, 12);
  const returned = await context.deliveryReturn({ deliveryId: 'delivery-001' });
  assert.equal(returned.state, 'RETURNED');
  assert.equal(sends.length, 3);
  const returnedAgain = await context.deliveryReturn({ deliveryId: 'delivery-001' });
  assert.equal(returnedAgain.replayed, true);
  assert.equal(sends.length, 3);
  const manager = await context.deliveryManagerStatus({ deliveryId: 'delivery-001' });
  assert.equal(manager.state, 'RETURNED');
  assert.equal(manager.managerResponseText, 'manager next');
  assert.equal(manager.managerResponseLength, 12);
  assert.equal(sends[3].tabId, 10);
  assert.equal(sends[3].message.relayId, 'delivery-001');
  assert.equal(sends[3].message.afterAssistantCount, 3);
  const observedAgain = await context.deliveryManagerStatus({ deliveryId: 'delivery-001' });
  assert.equal(observedAgain.managerResponseSha256, manager.managerResponseSha256);
  assert.equal(sends.filter(item => item.message.type === 'relay:simpleExecute').length, 2);
  const terminal = storage.deliveryLedgerMirrorV1['delivery-001'];
  const baselineCount = terminal.managerBeforeAssistantCount;
  delete terminal.managerBeforeAssistantCount;
  const noBaseline = await context.deliveryManagerStatus({ deliveryId: 'delivery-001' });
  assert.equal(noBaseline.ok, false);
  assert.equal(noBaseline.error, 'DELIVERY_MANAGER_BASELINE_NOT_CAPTURED');
  terminal.managerBeforeAssistantCount = baselineCount;
  // A changed answer on the exact turn must never silently replace a captured decision.
  const originalSend = context.sendToChatTab;
  context.sendToChatTab = async (tabId, message) => {
    if (tabId === 10 && message.type === 'relay:simpleReadReply') {
      return { ok: true, conversationKey: message.conversationKey, responseText: 'tampered' };
    }
    return originalSend(tabId, message);
  };
  const changed = await context.deliveryManagerStatus({ deliveryId: 'delivery-001' });
  assert.equal(changed.ok, false);
  assert.equal(changed.error, 'DELIVERY_MANAGER_REPLY_CHANGED');
  context.sendToChatTab = originalSend;
  for (let index = 0; index < 66; index += 1) {
    await context.writeDeliveryLedgerMirror(`active-${index}`, {
      deliveryId: `active-${index}`, state: 'SENT_WAITING', updatedAt: index,
    });
  }
  assert.equal(Object.values(storage.deliveryLedgerMirrorV1)
    .filter((item) => item.state === 'SENT_WAITING').length, 66);
  console.log('delivery ledger service v1: PASS');
})().catch((error) => { console.error(error); process.exit(1); });
