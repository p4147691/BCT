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
let orphanDraftSha256 = '';
let failNextExecuteUnknownApplied = false;
const context = {
  console, TextEncoder, crypto: webcrypto,
  RelayCore: {
    conversationKey(url) { return String(url).split('/c/')[1] || ''; },
    normalizeMessageText(value) {
      return String(value || '').replace(/\r\n?/g, '\n').replace(/\u00a0/g, ' ')
        .split('\n').map((line) => line.replace(/[ \t]+$/g, '')).join('\n').trim();
    },
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
      if (message.expectedResponseSha256) {
        return { ok: true, retired: true, effectState: 'APPLIED',
          relayId: message.relayId, conversationKey: message.conversationKey,
          requestSha256: message.expectedRequestSha256,
          responseSha256: message.expectedResponseSha256,
          responseLength: message.expectedResponseLength, executionAbsent: true };
      }
      return { ok: true, retired: true, relayId: message.relayId };
    }
    if (message.type === 'relay:retireComposerDraft') {
      controlCalls.push({ tabId, message });
      if (!orphanDraftSha256 || message.expectedDraftSha256 !== orphanDraftSha256) {
        return { ok: false, retired: false, effectState: 'NOT_APPLIED',
          error: 'RELAY_DRAFT_RETIRE_HASH_MISMATCH' };
      }
      targetComposerEmpty = true;
      return { ok: true, retired: true, effectState: 'APPLIED',
        conversationKey: message.conversationKey,
        draftSha256: orphanDraftSha256, draftLength: 321, composerEmpty: true,
        retiredExecutionId: message.supersededDeliveryId };
    }
    if (message.type === 'relay:exactUserTurnProof') {
      controlCalls.push({ tabId, message });
      return { ok: true, deliveryId: message.deliveryId,
        conversationKey: message.conversationKey,
        submittedSha256: message.submittedSha256,
        turnKey: 'semantic:user:' + message.deliveryId,
        beforeAssistantCount: 3 };
    }
    sends.push({ tabId, message });
    if (message.type === 'relay:simpleReadReply') {
      return { ok: true, conversationKey: message.conversationKey,
        responseText: tabId === 10 ? 'manager next' : 'worker reply\n' };
    }
    if (message.type === 'relay:simpleExecute' && failNextExecuteBusy) {
      failNextExecuteBusy = false;
      return { ok: false, submitted: false, effectState: 'NOT_APPLIED',
        error: 'RELAY_TARGET_GENERATING' };
    }
    if (message.type === 'relay:simpleExecute' && failNextExecuteUnknownApplied) {
      failNextExecuteUnknownApplied = false;
      return { ok: false, submitted: false, effectState: 'UNKNOWN',
        error: 'RELAY_DRAFT_CLEAR_UNPROVEN' };
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
  const text = 'one exact message\n';
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
  assert.equal(captured.responseLength, 13);
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
  const managerRetire = controlCalls.find(item => item.tabId === 10
    && item.message.type === 'relay:retireExecution'
    && item.message.relayId === 'delivery-001').message;
  assert.equal(managerRetire.expectedRequestSha256,
    storage.deliveryLedgerMirrorV1['delivery-001'].managerReturnSubmittedSha256);
  assert.notEqual(managerRetire.expectedRequestSha256, returned.managerReturnSha256);
  assert.equal(managerRetire.expectedResponseSha256, manager.managerResponseSha256);
  assert.equal(managerRetire.expectedResponseLength, manager.managerResponseLength);

  const workerRetire = controlCalls.find(item => item.tabId === 20
    && item.message.type === 'relay:retireExecution'
    && item.message.relayId === 'delivery-001').message;
  assert.equal(workerRetire.expectedRequestSha256,
    await context.relaySha256(context.RelayCore.normalizeMessageText(text)));
  assert.notEqual(workerRetire.expectedRequestSha256, requestSha256);
  assert.equal(workerRetire.expectedResponseSha256, captured.responseSha256);
  assert.equal(workerRetire.expectedResponseLength, captured.responseLength);
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

  // A lost activation ACK is reconciled from one exact Manager user turn.
  const reconcileIdentity = { ...identity, deliveryId: 'delivery-return-reconciled' };
  await context.deliveryStart(reconcileIdentity);
  await context.deliveryStatus({ deliveryId: reconcileIdentity.deliveryId });
  failNextExecuteUnknownApplied = true;
  const returnReconciled = await context.deliveryReturn({
    deliveryId: reconcileIdentity.deliveryId,
  });
  assert.equal(returnReconciled.ok, true);
  assert.equal(returnReconciled.state, 'RETURNED');
  assert.equal(returnReconciled.reconciled, true);
  assert.equal(storage.deliveryLedgerMirrorV1[reconcileIdentity.deliveryId]
    .managerReturnReconciled, true);
  assert.equal(controlCalls.some(item => item.tabId === 10
    && item.message.type === 'relay:exactUserTurnProof'
    && item.message.deliveryId === reconcileIdentity.deliveryId), true);

  // If exact turn reconciliation succeeds but Manager reply readback is still
  // pending, preserve that proof so Core can promote the same Delivery without
  // resending the return message.
  const pendingIdentity = { ...identity, deliveryId: 'delivery-return-pending-readback' };
  await context.deliveryStart(pendingIdentity);
  await context.deliveryStatus({ deliveryId: pendingIdentity.deliveryId });
  const pendingOriginalSend = context.sendToChatTab;
  context.sendToChatTab = async (tabId, message) => {
    if (message.type === 'relay:exactUserTurnProof') {
      return { ok: false, error: 'RELAY_EXACT_USER_TURN_NOT_FOUND' };
    }
    return pendingOriginalSend(tabId, message);
  };
  failNextExecuteUnknownApplied = true;
  const pendingUnknown = await context.deliveryReturn({
    deliveryId: pendingIdentity.deliveryId,
  });
  assert.equal(pendingUnknown.state, 'NEEDS_REVIEW');
  context.sendToChatTab = async (tabId, message) => {
    if (message.type === 'relay:simpleReadReply') {
      return { ok: false, error: 'SIMPLE_RELAY_ROUTE_RECORD_MISSING' };
    }
    return pendingOriginalSend(tabId, message);
  };
  const pendingReconciled = await context.deliveryManagerStatus({
    deliveryId: pendingIdentity.deliveryId,
  });
  assert.equal(pendingReconciled.ok, true);
  assert.equal(pendingReconciled.pending, true);
  assert.equal(pendingReconciled.state, 'RETURNED');
  assert.equal(pendingReconciled.reconciled, true);
  context.sendToChatTab = pendingOriginalSend;

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
  const footer = '\n[/BCT_CURRENT_WORKER_RESULT_FULL]\n후속 작업 판단\n';
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

  // A terminal Manager receipt created by an older RCC has no normalized
  // submission hash. The first retirement remains NOT_APPLIED, then the
  // content-proven normalized identity is adopted and retired exactly once.
  context.getChatTabs = tabsBefore;
  const legacyText = 'legacy return with trailing whitespace\n';
  const legacyIdentity = { ...identity, deliveryId: 'delivery-legacy', text: legacyText,
    requestSha256: await context.relaySha256(legacyText) };
  await context.deliveryStart(legacyIdentity);
  await context.deliveryStatus({ deliveryId: 'delivery-legacy' });
  const legacyReturn = await context.deliveryReturn({ deliveryId: 'delivery-legacy',
    managerReturnHeader: '[BCT_CURRENT_WORKER_RESULT_FULL]\n',
    managerReturnFooter: '\n[/BCT_CURRENT_WORKER_RESULT_FULL]\n' });
  const legacyReceipt = storage.deliveryLedgerMirrorV1['delivery-legacy'];
  const legacySubmittedSha256 = legacyReceipt.managerReturnSubmittedSha256;
  assert.notEqual(legacySubmittedSha256, legacyReturn.managerReturnSha256);
  delete legacyReceipt.managerReturnSubmittedSha256;
  const sendBeforeLegacyRetire = context.sendToChatTab;
  const legacyRetireRequests = [];
  context.sendToChatTab = async (tabId, message) => {
    if (tabId === 10 && message.type === 'relay:retireExecution'
        && message.relayId === 'delivery-legacy') {
      legacyRetireRequests.push(message.expectedRequestSha256);
      if (message.expectedRequestSha256 !== legacySubmittedSha256) {
        return { ok: false, retired: false, effectState: 'NOT_APPLIED',
          error: 'RELAY_RETIRE_REQUEST_IDENTITY_MISMATCH',
          requestSha256: legacySubmittedSha256 };
      }
      activeRelayIds.delete(10);
      return { ok: true, retired: true, effectState: 'APPLIED',
        relayId: message.relayId, conversationKey: message.conversationKey,
        requestSha256: legacySubmittedSha256,
        responseSha256: message.expectedResponseSha256,
        responseLength: message.expectedResponseLength, executionAbsent: true };
    }
    return sendBeforeLegacyRetire(tabId, message);
  };
  const legacyObserved = await context.deliveryManagerStatus({ deliveryId: 'delivery-legacy' });
  assert.equal(legacyObserved.managerResponseText, 'manager next');
  assert.deepEqual(legacyRetireRequests,
    [legacyReturn.managerReturnSha256, legacySubmittedSha256]);
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-legacy'].managerExecutionRetired, true);
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-legacy'].managerReturnSubmittedSha256,
    legacySubmittedSha256);
  context.sendToChatTab = sendBeforeLegacyRetire;
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

  // A changed user instruction can retire an exact queued Delivery only
  // before a physical submit. Cancellation clears the retained plaintext and
  // later endpoint activity must not resurrect it.
  const cancelIdentity = { ...identity, deliveryId: 'delivery-cancelled' };
  const cancelQueued = await context.deliveryStart(cancelIdentity);
  assert.equal(cancelQueued.state, 'WAITING_TARGET');
  const beforeCancelSubmit = sends.filter(
    item => item.message.type === 'relay:simpleExecute').length;
  const cancelled = await context.deliveryCancel({ deliveryId: 'delivery-cancelled' });
  assert.equal(cancelled.ok, true);
  assert.equal(cancelled.cancelled, true);
  assert.equal(cancelled.state, 'NOT_APPLIED');
  assert.equal(cancelled.error, 'DELIVERY_CANCELLED_PRE_SUBMIT');
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-cancelled'].requestText, '');
  const cancelledAgain = await context.deliveryCancel({ deliveryId: 'delivery-cancelled' });
  assert.equal(cancelledAgain.replayed, true);
  assert.equal(cancelledAgain.cancelled, true);
  targetGenerating = false;
  const resumed = await context.resumeWaitingDeliveriesForEndpoint({
    conversationKey: identity.workerConversationKey,
    generating: false, presence: 'OPEN',
  });
  assert.equal(resumed[0].state, 'SENT_WAITING');
  assert.equal(sends.filter(
    item => item.message.type === 'relay:simpleExecute').length, beforeCancelSubmit + 1);
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-cancelled'].state, 'NOT_APPLIED');

  assert.equal(sends.filter(
    item => item.message.type === 'relay:simpleExecute').length, beforeQueuedSubmit + 1);
  const resumedCaptured = await context.deliveryStatus({ deliveryId: 'delivery-queued' });
  assert.equal(resumedCaptured.state, 'REPLY_CAPTURED');
  const lateCancel = await context.deliveryCancel({ deliveryId: 'delivery-queued' });
  assert.equal(lateCancel.ok, false);
  assert.equal(lateCancel.cancelled, false);
  assert.equal(lateCancel.error, 'DELIVERY_CANCEL_STATE_INVALID');

  // An occupied composer is also queued and never overwritten.
  targetComposerEmpty = false;
  const occupied = await context.deliveryStart({
    ...identity, deliveryId: 'delivery-occupied',
  });
  assert.equal(occupied.state, 'WAITING_TARGET');
  assert.equal(occupied.waitingReason, 'TARGET_COMPOSER_OCCUPIED');
  orphanDraftSha256 = 'a'.repeat(64);
  await context.writeDeliveryLedgerMirror('delivery-superseded', {
    deliveryId: 'delivery-superseded', state: 'NEEDS_REVIEW',
    managerConversationKey: identity.managerConversationKey,
    workerConversationKey: identity.workerConversationKey,
    requestSha256: orphanDraftSha256, updatedAt: Date.now(),
  });
  const mismatch = await context.retireComposerDraftAndResume({
    conversationKey: identity.workerConversationKey,
    expectedDraftSha256: 'b'.repeat(64),
    resumeDeliveryId: 'delivery-occupied',
    supersededDeliveryId: 'delivery-superseded',
  });
  assert.equal(mismatch.ok, false);
  assert.equal(mismatch.effectState, 'NOT_APPLIED');
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-occupied'].state, 'WAITING_TARGET');
  const occupiedResumed = await context.retireComposerDraftAndResume({
    conversationKey: identity.workerConversationKey,
    expectedDraftSha256: orphanDraftSha256,
    resumeDeliveryId: 'delivery-occupied',
    supersededDeliveryId: 'delivery-superseded',
  });
  assert.equal(occupiedResumed.ok, true);
  assert.equal(occupiedResumed.retired, true);
  assert.equal(occupiedResumed.resumedDelivery.state, 'SENT_WAITING');
  assert.equal(occupiedResumed.draftLength, 321);
  assert.equal(occupiedResumed.retiredExecutionId, 'delivery-superseded');
  await context.deliveryStatus({ deliveryId: 'delivery-occupied' });

  const recoveredRequestSha = 'c'.repeat(64);
  const recoveredResponseSha = 'd'.repeat(64);
  await context.writeDeliveryLedgerMirror('delivery-recovered', {
    deliveryId: 'delivery-recovered', state: 'NEEDS_REVIEW',
    managerConversationKey: identity.managerConversationKey,
    workerConversationKey: identity.workerConversationKey,
    requestSha256: recoveredRequestSha, updatedAt: Date.now(),
  });
  activeRelayIds.set(20, 'delivery-recovered');
  const recoveredRetired = await context.retireRecoveredExecution({
    deliveryId: 'delivery-recovered',
    conversationKey: identity.workerConversationKey,
    expectedRequestSha256: recoveredRequestSha,
    expectedResponseSha256: recoveredResponseSha,
    expectedResponseLength: 76,
  });
  assert.equal(recoveredRetired.ok, true);
  assert.equal(recoveredRetired.executionAbsent, true);
  assert.equal(recoveredRetired.responseSha256, recoveredResponseSha);

  // A Manager that is still generating keeps the exact return outside the
  // composer and resumes it once after the endpoint reports idle.
  activeRelayIds.delete(10);
  targetGenerating = false;
  const queuedReturnIdentity = { ...identity, deliveryId: 'delivery-return-queued' };
  await context.deliveryStart(queuedReturnIdentity);
  await context.deliveryStatus({ deliveryId: 'delivery-return-queued' });
  targetGenerating = true;
  const beforeQueuedReturn = sends.filter(
    item => item.message.type === 'relay:simpleExecute').length;
  const queuedReturn = await context.deliveryReturn({ deliveryId: 'delivery-return-queued' });
  assert.equal(queuedReturn.ok, true);
  assert.equal(queuedReturn.state, 'REPLY_CAPTURED');
  assert.equal(queuedReturn.pending, true);
  assert.equal(queuedReturn.queued, true);
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-return-queued'].managerReturnQueued, true);
  assert.equal(sends.filter(
    item => item.message.type === 'relay:simpleExecute').length, beforeQueuedReturn);
  targetGenerating = false;
  const resumedReturn = await context.resumeWaitingDeliveriesForEndpoint({
    conversationKey: identity.managerConversationKey, generating: false, presence: 'OPEN',
  });
  assert.equal(resumedReturn[0].state, 'RETURNED');
  assert.equal(storage.deliveryLedgerMirrorV1['delivery-return-queued'].managerReturnQueued, false);
  assert.equal(sends.filter(
    item => item.message.type === 'relay:simpleExecute').length, beforeQueuedReturn + 1);

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
