const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { TextEncoder } = require('util');
const { webcrypto } = require('crypto');

const storage = {};
const sends = [];
const controlCalls = [];
let targetGenerating = false;
let targetComposerEmpty = true;
const activeRelayIds = new Map();
let failNextExecuteBusy = false;
let failNextRetireAck = false;
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
    if (message.type === 'relay:deliveryReadiness') {
      controlCalls.push({ tabId, message });
      return { ok: true, conversationKey: message.conversationKey,
        generating: targetGenerating, composerEmpty: targetComposerEmpty,
        activeRelayId: activeRelayIds.get(tabId) || '' };
    }
    if (message.type === 'relay:retireExecution') {
      controlCalls.push({ tabId, message });
      if (failNextRetireAck) {
        failNextRetireAck = false;
        return { ok: false, retired: false, error: 'TEST_RETIRE_ACK_LOST' };
      }
      if (activeRelayIds.get(tabId) === message.relayId) activeRelayIds.delete(tabId);
      return { ok: true, retired: true, relayId: message.relayId };
    }
    sends.push({ tabId, message });
    if (message.type === 'relay:simpleReadReply') {
      return { ok: true, conversationKey: message.conversationKey,
        responseText: tabId === 10 ? 'manager next' : 'worker reply' };
    }
    if (message.type === 'relay:simpleExecute' && failNextExecuteBusy) {
      failNextExecuteBusy = false;
      return { ok: false, submitted: false, effectState: 'NOT_APPLIED',
        error: 'RELAY_TARGET_GENERATING' };
    }
    activeRelayIds.set(tabId, message.relayId);
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
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-001'].managerExecutionRetired, true);
  assert.equal(activeRelayIds.has(10), false);
  assert.equal(controlCalls.filter(item => item.tabId === 10
    && item.message.type === 'relay:retireExecution'
    && item.message.relayId === 'delivery-001').length, 1);
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

  // New manager return is ONE user turn containing the FULL current Worker result.
  // The Worker tab may disappear after its response is captured.
  const tabsBefore = context.getChatTabs;
  const sendBefore = context.sendToChatTab;
  const actualWorkerResult = '이번 차 전체 처리 결과 📦\n검증 확인';
  context.sendToChatTab = async (tabId, message) => {
    if (tabId === 20 && message.type === 'relay:simpleReadReply') {
      return { ok: true, conversationKey: message.conversationKey,
        responseText: actualWorkerResult };
    }
    return sendBefore(tabId, message);
  };
  const nextIdentity = { ...identity, deliveryId: 'delivery-002' };
  const nextStart = await context.deliveryStart(nextIdentity);
  assert.equal(nextStart.state, 'SENT_WAITING');
  const nextCaptured = await context.deliveryStatus({ deliveryId: 'delivery-002' });
  assert.equal(nextCaptured.state, 'REPLY_CAPTURED');
  assert.equal(nextCaptured.responseLength, actualWorkerResult.length);
  context.getChatTabs = async () => [{
    id: 10, windowId: 100,
    url: 'https://chatgpt.com/c/11111111-1111-1111-1111-111111111111',
  }];
  const header = 'Manager 지시\n[BCT_CURRENT_WORKER_RESULT_FULL]\n';
  const footer = '\n[/BCT_CURRENT_WORKER_RESULT_FULL]\n후속 작업 판단';
  const countBefore = sends.length;
  const framed = await context.deliveryReturn({
    deliveryId: 'delivery-002', managerReturnHeader: header,
    managerReturnFooter: footer, managerReturnSettingsSha256: 'defaults',
  });
  assert.equal(framed.state, 'RETURNED');
  assert.equal(sends.length, countBefore + 1);
  assert.equal(sends.at(-1).tabId, 10);
  assert.equal(sends.at(-1).message.text, header + actualWorkerResult + footer);
  assert.equal(framed.managerReturnSha256,
    await context.relaySha256(header + actualWorkerResult + footer));
  assert.equal(framed.managerReturnLength, (header + actualWorkerResult + footer).length);
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-002'].responseText, actualWorkerResult);
  failNextRetireAck = true;
  const checkWithoutWorker = await context.deliveryManagerStatus({ deliveryId: 'delivery-002' });
  assert.equal(checkWithoutWorker.managerResponseText, 'manager next');
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-002'].managerExecutionRetired, undefined);
  assert.equal(activeRelayIds.get(10), 'delivery-002');
  const retiredOnReadback = await context.deliveryManagerStatus({ deliveryId: 'delivery-002' });
  assert.equal(retiredOnReadback.managerResponseText, 'manager next');
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-002'].managerExecutionRetired, true);
  assert.equal(activeRelayIds.has(10), false);
  const unchangedCount = sends.length;
  const duplicateReturn = await context.deliveryReturn({
    deliveryId: 'delivery-002', managerReturnHeader: 'changed',
    managerReturnFooter: 'changed',
  });
  assert.equal(duplicateReturn.replayed, true);
  assert.equal(sends.length, unchangedCount);
  // A frame that cannot carry the full result must fail BEFORE an additional submit.
  context.getChatTabs = tabsBefore;
  const bigIdentity = { ...identity, deliveryId: 'delivery-003' };
  await context.deliveryStart(bigIdentity);
  await context.deliveryStatus({ deliveryId: 'delivery-003' });
  const beforeOversize = sends.length;
  const oversize = await context.deliveryReturn({
    deliveryId: 'delivery-003',
    managerReturnHeader: 'X'.repeat(12000) + '[BCT_CURRENT_WORKER_RESULT_FULL]',
    managerReturnFooter: '[/BCT_CURRENT_WORKER_RESULT_FULL]',
  });
  assert.equal(oversize.ok, false);
  assert.equal(oversize.error, 'DELIVERY_MANAGER_RETURN_TOO_LARGE');
  assert.equal(sends.length, beforeOversize);
  context.sendToChatTab = sendBefore;
  context.getChatTabs = tabsBefore;

  // A visible send control never overrides a generating/busy signal. The
  // exact payload remains durable outside the composer and resumes once.
  targetGenerating = true;
  const queuedIdentity = { ...identity, deliveryId: 'delivery-queued' };
  const beforeQueuedSubmit = sends.filter(
    item => item.message.type === 'relay:simpleExecute').length;
  const queued = await context.deliveryStart(queuedIdentity);
  assert.equal(queued.ok, true);
  assert.equal(queued.state, 'WAITING_TARGET');
  assert.equal(queued.queued, true);
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-queued'].requestText, text);
  assert.equal(sends.filter(
    item => item.message.type === 'relay:simpleExecute').length, beforeQueuedSubmit);
  targetGenerating = false;
  const resumed = await context.resumeWaitingDeliveriesForEndpoint({
    conversationKey: identity.workerConversationKey,
    generating: false, presence: 'OPEN',
  });
  assert.equal(resumed[0].state, 'SENT_WAITING');
  assert.equal(sends.filter(
    item => item.message.type === 'relay:simpleExecute').length, beforeQueuedSubmit + 1);
  const resumedCaptured = await context.deliveryStatus({ deliveryId: 'delivery-queued' });
  assert.equal(resumedCaptured.state, 'REPLY_CAPTURED');

  // An occupied composer is also queued and never overwritten.
  targetComposerEmpty = false;
  const occupied = await context.deliveryStart({
    ...identity, deliveryId: 'delivery-occupied',
  });
  assert.equal(occupied.state, 'WAITING_TARGET');
  assert.equal(occupied.waitingReason, 'TARGET_COMPOSER_OCCUPIED');
  targetComposerEmpty = true;
  const occupiedResumed = await context.resumeWaitingDeliveriesForEndpoint({
    conversationKey: identity.workerConversationKey,
    generating: false, presence: 'OPEN',
  });
  assert.equal(occupiedResumed[0].state, 'SENT_WAITING');
  await context.deliveryStatus({ deliveryId: 'delivery-occupied' });

  // If generation begins after the background readiness probe but before the
  // content activation boundary, the content guard returns to the queue.
  failNextExecuteBusy = true;
  const raced = await context.deliveryStart({
    ...identity, deliveryId: 'delivery-raced-busy',
  });
  assert.equal(raced.state, 'WAITING_TARGET');
  assert.equal(raced.waitingReason, 'RELAY_TARGET_GENERATING');

  // A later delivery never overtakes an older waiting delivery for the same
  // Worker, even when the endpoint becomes idle between the two starts.
  targetGenerating = true;
  const fifoFirst = await context.deliveryStart({
    ...identity, deliveryId: 'delivery-fifo-first',
  });
  const fifoSecond = await context.deliveryStart({
    ...identity, deliveryId: 'delivery-fifo-second',
  });
  assert.equal(fifoFirst.state, 'WAITING_TARGET');
  assert.equal(fifoSecond.state, 'WAITING_TARGET');
  assert.equal(fifoSecond.waitingReason, 'TARGET_QUEUE_PREDECESSOR');

  for (let index = 0; index < 66; index += 1) {
    await context.writeDeliveryLedgerMirror(`active-${index}`, {
      deliveryId: `active-${index}`, state: 'SENT_WAITING', updatedAt: index,
    });
  }
  assert.equal(Object.values(storage.deliveryLedgerMirrorV1)
    .filter((item) => item.state === 'SENT_WAITING'
      && String(item.deliveryId || '').startsWith('active-')).length, 66);
  console.log('delivery ledger service v1: PASS');
})().catch((error) => { console.error(error); process.exit(1); });
