const DELIVERY_LEDGER_MIRROR_KEY = 'deliveryLedgerMirrorV1';
const deliveryResumeLocks = new Map();
let deliveryLedgerWriteTail = Promise.resolve();
let deliveryStartTail = Promise.resolve();
const DELIVERY_WAITABLE_ERRORS = new Set([
  'RELAY_TARGET_GENERATING', 'Target ChatGPT tab is already generating',
  'RELAY_COMPOSER_NOT_EMPTY', 'RELAY_SEND_BUTTON_NOT_READY',
  'RELAY_EDITOR_FOCUS_OR_CARET_INVALID', 'RELAY_EDITOR_WAKE_FAILED',
  'RELAY_EDITOR_TEXT_MISMATCH', 'RELAY_SEND_BUTTON_CHANGED',
]);

function deliveryConversationKey(value) {
  const key = String(value || '').trim().toLowerCase();
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(key)) {
    throw new Error('DELIVERY_CONVERSATION_KEY_INVALID');
  }
  return key;
}

function deliveryId(value) {
  const id = String(value || '').trim();
  if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(id)) throw new Error('DELIVERY_ID_INVALID');
  return id;
}

async function deliverySubmittedSha256(value) {
  return relaySha256(RelayCore.normalizeMessageText(String(value || '')));
}

async function readDeliveryLedgerMirror() {
  const data = await stateRepository.getLocal(DELIVERY_LEDGER_MIRROR_KEY);
  const value = data[DELIVERY_LEDGER_MIRROR_KEY];
  return value && typeof value === 'object' ? value : {};
}

async function writeDeliveryLedgerMirror(id, receipt) {
  const operation = deliveryLedgerWriteTail.then(async () => {
    const ledger = await readDeliveryLedgerMirror();
    ledger[id] = receipt;
    const entries = Object.entries(ledger)
      .sort((a, b) => Number(b[1]?.updatedAt || 0) - Number(a[1]?.updatedAt || 0));
    const activeStates = new Set(['NOT_SENT', 'WAITING_TARGET', 'SENT_WAITING', 'REPLY_CAPTURED']);
    // Never evict a delivery that still owns the only reply text or duplicate
    // submission fence. Bound only terminal audit mirrors; BCT owns durable
    // history for those terminal rows.
    const active = entries.filter(([, value]) => activeStates.has(value?.state));
    const terminal = entries.filter(([, value]) => !activeStates.has(value?.state)).slice(0, 64);
    const keep = [...active, ...terminal];
    await stateRepository.setLocal({ [DELIVERY_LEDGER_MIRROR_KEY]: Object.fromEntries(keep) });
    return receipt;
  });
  deliveryLedgerWriteTail = operation.catch(() => {});
  return operation;
}

function deliveryTabs(tabs, managerConversationKey, workerConversationKey) {
  const manager = tabs.filter((tab) =>
    RelayCore.conversationKey(tab.url || '') === managerConversationKey);
  const worker = tabs.filter((tab) =>
    RelayCore.conversationKey(tab.url || '') === workerConversationKey);
  if (manager.length !== 1 || worker.length !== 1) {
    throw new Error('DELIVERY_ENDPOINT_NOT_UNIQUE_OR_OPEN');
  }
  return { manager: manager[0], worker: worker[0] };
}

function singleDeliveryTab(tabs, conversationKey) {
  const matches = tabs.filter((tab) =>
    RelayCore.conversationKey(tab.url || '') === conversationKey);
  if (matches.length !== 1) throw new Error('DELIVERY_ENDPOINT_NOT_UNIQUE_OR_OPEN');
  return matches[0];
}

function publicDeliveryReceipt(receipt) {
  if (!receipt || typeof receipt !== 'object') return null;
  return {
    deliveryId: String(receipt.deliveryId || ''),
    state: String(receipt.state || ''),
    managerConversationKey: String(receipt.managerConversationKey || ''),
    workerConversationKey: String(receipt.workerConversationKey || ''),
    requestSha256: String(receipt.requestSha256 || ''),
    deliverySettingsSha256: String(receipt.deliverySettingsSha256 || ''),
    responseSha256: String(receipt.responseSha256 || ''),
    responseLength: Number.isInteger(receipt.responseLength) ? receipt.responseLength : null,
    managerReturnSha256: String(receipt.managerReturnSha256 || ''),
    managerReturnSettingsSha256: String(receipt.managerReturnSettingsSha256 || ''),
    managerReturnLength: Number.isInteger(receipt.managerReturnLength)
      ? receipt.managerReturnLength : null,
    managerResponseSha256: String(receipt.managerResponseSha256 || ''),
    managerResponseLength: Number.isInteger(receipt.managerResponseLength)
      ? receipt.managerResponseLength : null,
    workerTabId: Number.isInteger(receipt.workerTabId) ? receipt.workerTabId : null,
    workerWindowId: Number.isInteger(receipt.workerWindowId) ? receipt.workerWindowId : null,
    managerTabId: Number.isInteger(receipt.managerTabId) ? receipt.managerTabId : null,
    managerWindowId: Number.isInteger(receipt.managerWindowId) ? receipt.managerWindowId : null,
    queued: receipt.state === 'WAITING_TARGET' || receipt.managerReturnQueued === true,
    waitingReason: String(receipt.managerReturnWaitingReason || receipt.waitingReason || ''),
    queuedAt: Number(receipt.managerReturnQueuedAt || receipt.queuedAt || 0) || null,
    error: String(receipt.error || ''),
  };
}

function deliverySubmitPolicy(message) {
  const targetBusyPolicy = String(message.targetBusyPolicy || 'queue_until_idle');
  const composerWakeMode = String(message.composerWakeMode || 'trailing_space_once');
  const sendButtonWaitMs = Number(message.sendButtonWaitMs ?? 1000);
  const deliverySettingsSha256 = String(message.deliverySettingsSha256 || 'defaults');
  if (!['queue_until_idle', 'reject'].includes(targetBusyPolicy)
      || !['trailing_space_once', 'none'].includes(composerWakeMode)
      || !Number.isInteger(sendButtonWaitMs) || sendButtonWaitMs < 0
      || sendButtonWaitMs > 8000
      || (deliverySettingsSha256 !== 'defaults'
        && !/^[a-f0-9]{64}$/.test(deliverySettingsSha256))) {
    throw new Error('DELIVERY_SUBMIT_POLICY_INVALID');
  }
  return { targetBusyPolicy, composerWakeMode, sendButtonWaitMs,
    deliverySettingsSha256 };
}

async function inspectDeliveryReadiness(tab, receipt) {
  return inspectConversationReadiness(tab, receipt, receipt.workerConversationKey);
}

async function inspectConversationReadiness(tab, receipt, conversationKey) {
  const value = await sendToChatTab(tab.id, {
    type: 'relay:deliveryReadiness',
    conversationKey,
  });
  if (value?.ok !== true || value.conversationKey !== conversationKey) {
    return { ready: false, terminal: true, reason: 'DELIVERY_TARGET_IDENTITY_MISMATCH' };
  }
  if (value.generating === true) {
    return { ready: false, terminal: false, reason: 'TARGET_GENERATING' };
  }
  if (value.composerEmpty !== true) {
    return { ready: false, terminal: false, reason: 'TARGET_COMPOSER_OCCUPIED' };
  }
  const activeRelayId = String(value.activeRelayId || '');
  if (activeRelayId && activeRelayId !== receipt.deliveryId) {
    return { ready: false, terminal: false, reason: 'TARGET_PRIOR_RELAY_ACTIVE' };
  }
  return { ready: true, terminal: false, reason: 'TARGET_IDLE' };
}

async function waitOrRejectDelivery(receipt, reason) {
  if (receipt.targetBusyPolicy === 'reject') {
    const rejected = { ...receipt, state: 'NOT_APPLIED', waitingReason: '',
      error: reason, requestText: '', updatedAt: Date.now() };
    return writeDeliveryLedgerMirror(receipt.deliveryId, rejected);
  }
  const queued = { ...receipt, state: 'WAITING_TARGET',
    queuedAt: Number(receipt.queuedAt || 0) || Date.now(),
    waitingReason: reason, error: '', updatedAt: Date.now() };
  return writeDeliveryLedgerMirror(receipt.deliveryId, queued);
}

async function attemptDeliverySubmission(receipt, workerTab) {
  let readiness;
  try {
    readiness = await inspectDeliveryReadiness(workerTab, receipt);
  } catch (error) {
    return waitOrRejectDelivery(receipt,
      'TARGET_READINESS_UNAVAILABLE:' + String(error?.message || error || 'unknown').slice(0, 80));
  }
  if (!readiness.ready) {
    if (readiness.terminal) {
      const failed = { ...receipt, state: 'NOT_APPLIED', waitingReason: '',
        requestText: '', error: readiness.reason, updatedAt: Date.now() };
      return writeDeliveryLedgerMirror(receipt.deliveryId, failed);
    }
    return waitOrRejectDelivery(receipt, readiness.reason);
  }
  let ack;
  try {
    ack = await sendToChatTab(workerTab.id, {
      type: 'relay:simpleExecute', relayId: receipt.deliveryId,
      conversationKey: receipt.workerConversationKey, text: receipt.requestText,
      composerWakeMode: receipt.composerWakeMode,
      sendButtonWaitMs: receipt.sendButtonWaitMs,
    });
  } catch (error) {
    const unresolved = { ...receipt, state: 'NEEDS_REVIEW', waitingReason: '',
      requestText: '',
      error: String(error?.message || error || 'DELIVERY_TRANSPORT_UNKNOWN').slice(0, 128),
      updatedAt: Date.now() };
    return writeDeliveryLedgerMirror(receipt.deliveryId, unresolved);
  }
  if (ack?.ok === true && ack.submitted === true
      && ack.conversationKey === receipt.workerConversationKey) {
    const submitted = { ...receipt, state: 'SENT_WAITING', waitingReason: '', error: '',
      requestText: '',
      beforeAssistantCount: Number(ack.beforeAssistantCount || 0),
      workerTabId: workerTab.id, workerWindowId: workerTab.windowId,
      updatedAt: Date.now() };
    return writeDeliveryLedgerMirror(receipt.deliveryId, submitted);
  }
  const error = String(ack?.error || 'DELIVERY_ACK_INVALID').slice(0, 128);
  if (ack?.effectState === 'NOT_APPLIED' && DELIVERY_WAITABLE_ERRORS.has(error)) {
    return waitOrRejectDelivery(receipt, error);
  }
  const state = ack?.effectState === 'NOT_APPLIED' ? 'NOT_APPLIED' : 'NEEDS_REVIEW';
  const unresolved = { ...receipt, state, waitingReason: '',
    requestText: '',
    updatedAt: Date.now(), error };
  return writeDeliveryLedgerMirror(receipt.deliveryId, unresolved);
}

async function resumeWaitingDelivery(deliveryIdValue) {
  const id = deliveryId(deliveryIdValue);
  if (deliveryResumeLocks.has(id)) return deliveryResumeLocks.get(id);
  const operation = (async () => {
    const ledger = await readDeliveryLedgerMirror();
    const receipt = ledger[id];
    if (!receipt || receipt.state !== 'WAITING_TARGET') return receipt || null;
    let workerTab;
    try {
      workerTab = singleDeliveryTab(await getChatTabs(), receipt.workerConversationKey);
    } catch (_) {
      return waitOrRejectDelivery(receipt, 'TARGET_TAB_NOT_UNIQUELY_OPEN');
    }
    return attemptDeliverySubmission(receipt, workerTab);
  })().finally(() => deliveryResumeLocks.delete(id));
  deliveryResumeLocks.set(id, operation);
  return operation;
}

async function resumeWaitingDeliveriesForEndpoint(endpoint) {
  if (!endpoint || endpoint.generating === true || endpoint.presence === 'OFFLINE') return [];
  const conversationKey = String(endpoint.conversationKey || '').trim().toLowerCase();
  if (!conversationKey) return [];
  let ledger = await readDeliveryLedgerMirror();
  // A Manager reply created by a prior return owns the page-session relay
  // marker until its completed response is captured and retired.  Do this
  // before resuming the next queued return so one Manager turn cannot block
  // the next forever merely because nobody polled after it became idle.
  const returned = Object.values(ledger)
    .filter((item) => item?.state === 'RETURNED'
      && item.managerConversationKey === conversationKey
      && item.managerExecutionRetired !== true)
    .sort((a, b) => Number(a.updatedAt || 0) - Number(b.updatedAt || 0));
  for (const item of returned) await deliveryManagerStatus({ deliveryId: item.deliveryId });
  ledger = await readDeliveryLedgerMirror();
  const waitingReturns = Object.values(ledger)
    .filter((item) => item?.state === 'REPLY_CAPTURED'
      && item.managerConversationKey === conversationKey
      && item.managerReturnQueued === true)
    .sort((a, b) => Number(a.managerReturnQueuedAt || a.updatedAt || 0)
      - Number(b.managerReturnQueuedAt || b.updatedAt || 0));
  if (waitingReturns.length) {
    return [await resumeQueuedManagerReturn(waitingReturns[0].deliveryId)];
  }
  const waiting = Object.values(ledger)
    .filter((item) => item?.state === 'WAITING_TARGET'
      && item.workerConversationKey === conversationKey)
    .sort((a, b) => Number(a.queuedAt || a.updatedAt || 0)
      - Number(b.queuedAt || b.updatedAt || 0));
  if (!waiting.length) return [];
  // FIFO per Worker. A later item cannot overtake the first queued Delivery.
  return [await resumeWaitingDelivery(waiting[0].deliveryId)];
}

async function deliveryStartUnlocked(message) {
  const id = deliveryId(message.deliveryId);
  const managerConversationKey = deliveryConversationKey(message.managerConversationKey);
  const workerConversationKey = deliveryConversationKey(message.workerConversationKey);
  const text = String(message.text || '');
  const requestSha256 = String(message.requestSha256 || '').trim();
  let submitPolicy;
  try { submitPolicy = deliverySubmitPolicy(message); }
  catch (error) {
    return { ok: false, deliveryId: id, state: 'NOT_APPLIED',
      error: String(error?.message || error).slice(0, 128) };
  }
  if (managerConversationKey === workerConversationKey || !text || text.length > 12000
      || !/^[a-f0-9]{64}$/.test(requestSha256)
      || await relaySha256(text) !== requestSha256) {
    return { ok: false, deliveryId: id, state: 'NOT_APPLIED',
      error: 'DELIVERY_START_ARGUMENT_INVALID' };
  }
  const fingerprint = await relaySha256(JSON.stringify([
    id, managerConversationKey, workerConversationKey, requestSha256,
  ]));
  const ledger = await readDeliveryLedgerMirror();
  const existing = ledger[id];
  if (existing) {
    if (existing.fingerprint !== fingerprint) throw new Error('DELIVERY_ID_REUSE_MISMATCH');
    return { ok: !['NOT_APPLIED', 'NEEDS_REVIEW', 'FAILED'].includes(existing.state),
      replayed: true, ...publicDeliveryReceipt(existing) };
  }
  let tabs;
  try {
    tabs = deliveryTabs(await getChatTabs(), managerConversationKey, workerConversationKey);
  } catch (error) {
    return { ok: false, deliveryId: id, state: 'NOT_APPLIED',
      error: String(error?.message || error).slice(0, 128) };
  }
  const priorActive = Object.values(ledger).find((item) =>
    item?.workerConversationKey === workerConversationKey
      && (['NOT_SENT', 'WAITING_TARGET', 'SENT_WAITING'].includes(item.state)
        || (item.state === 'REPLY_CAPTURED' && item.workerExecutionRetired !== true)));
  const now = Date.now();
  const intent = {
    version: 1, deliveryId: id, fingerprint, managerConversationKey,
    workerConversationKey, requestSha256, requestText: text,
    requestSubmittedSha256: await deliverySubmittedSha256(text),
    ...submitPolicy, state: 'WAITING_TARGET', waitingReason: 'SUBMISSION_PENDING',
    createdAt: now, queuedAt: now, updatedAt: now,
  };
  await writeDeliveryLedgerMirror(id, intent);
  const receipt = priorActive
    ? await waitOrRejectDelivery(intent, 'TARGET_QUEUE_PREDECESSOR')
    : await resumeWaitingDelivery(id);
  return { ok: !['NOT_APPLIED', 'NEEDS_REVIEW', 'FAILED'].includes(receipt.state),
    ...publicDeliveryReceipt(receipt) };
}

async function deliveryStart(message) {
  const operation = deliveryStartTail.then(() => deliveryStartUnlocked(message));
  deliveryStartTail = operation.catch(() => {});
  return operation;
}

async function deliveryCancel(message) {
  const id = deliveryId(message.deliveryId);
  // A concurrent resume may already be proving or activating the physical
  // submit. Wait for that exact attempt and cancel only if it still proves
  // WAITING_TARGET. This command never guesses across the submit boundary.
  while (deliveryResumeLocks.has(id)) {
    try { await deliveryResumeLocks.get(id); } catch (_) {}
  }
  const operation = (async () => {
    const ledger = await readDeliveryLedgerMirror();
    const receipt = ledger[id];
    if (!receipt) return { ok: false, deliveryId: id, state: 'NEEDS_REVIEW',
      cancelled: false, error: 'DELIVERY_MIRROR_NOT_FOUND' };
    if (receipt.state === 'NOT_APPLIED'
        && receipt.error === 'DELIVERY_CANCELLED_PRE_SUBMIT') {
      return { ok: true, replayed: true, cancelled: true,
        ...publicDeliveryReceipt(receipt) };
    }
    if (receipt.state !== 'WAITING_TARGET') {
      return { ok: false, cancelled: false, ...publicDeliveryReceipt(receipt),
        error: 'DELIVERY_CANCEL_STATE_INVALID' };
    }
    const cancelled = await writeDeliveryLedgerMirror(id, {
      ...receipt, state: 'NOT_APPLIED', requestText: '', waitingReason: '',
      error: 'DELIVERY_CANCELLED_PRE_SUBMIT', cancelledAt: Date.now(),
      updatedAt: Date.now(),
    });
    return { ok: true, cancelled: true, ...publicDeliveryReceipt(cancelled) };
  })();
  deliveryResumeLocks.set(id, operation);
  try { return await operation; }
  finally {
    if (deliveryResumeLocks.get(id) === operation) deliveryResumeLocks.delete(id);
  }
}

async function retireComposerDraftAndResume(message) {
  const conversationKey = deliveryConversationKey(message.conversationKey);
  const expectedDraftSha256 = String(message.expectedDraftSha256 || '').trim().toLowerCase();
  const resumeDeliveryId = deliveryId(message.resumeDeliveryId);
  const supersededDeliveryId = deliveryId(message.supersededDeliveryId);
  if (!/^[a-f0-9]{64}$/.test(expectedDraftSha256)) {
    return { ok: false, retired: false, effectState: 'NOT_APPLIED',
      error: 'DELIVERY_DRAFT_RETIRE_HASH_INVALID' };
  }
  const ledger = await readDeliveryLedgerMirror();
  const queued = ledger[resumeDeliveryId];
  const superseded = ledger[supersededDeliveryId];
  if (!queued || queued.state !== 'WAITING_TARGET'
      || queued.workerConversationKey !== conversationKey) {
    return { ok: false, retired: false, effectState: 'NOT_APPLIED',
      error: 'DELIVERY_DRAFT_RETIRE_RESUME_IDENTITY_INVALID' };
  }
  if (!superseded || superseded.state !== 'NEEDS_REVIEW'
      || superseded.workerConversationKey !== conversationKey
      || superseded.requestSha256 !== expectedDraftSha256) {
    return { ok: false, retired: false, effectState: 'NOT_APPLIED',
      error: 'DELIVERY_DRAFT_RETIRE_SUPERSEDED_IDENTITY_INVALID' };
  }
  let workerTab;
  try {
    workerTab = singleDeliveryTab(await getChatTabs(), conversationKey);
  } catch (error) {
    return { ok: false, retired: false, effectState: 'NOT_APPLIED',
      error: String(error?.message || error).slice(0, 128) };
  }
  const retired = await sendToChatTab(workerTab.id, {
    type: 'relay:retireComposerDraft', conversationKey, expectedDraftSha256,
    supersededDeliveryId,
  });
  if (retired?.ok !== true || retired.retired !== true
      || retired.effectState !== 'APPLIED'
      || retired.conversationKey !== conversationKey
      || retired.draftSha256 !== expectedDraftSha256
      || !['', supersededDeliveryId].includes(String(retired.retiredExecutionId || ''))
      || retired.composerEmpty !== true) {
    return {
      ok: false, retired: false,
      effectState: String(retired?.effectState || 'UNKNOWN'),
      error: String(retired?.error || 'DELIVERY_DRAFT_RETIRE_ACK_INVALID').slice(0, 128),
      actualDraftSha256: String(retired?.actualDraftSha256 || ''),
    };
  }
  const resumed = await resumeWaitingDelivery(resumeDeliveryId);
  return {
    ok: true, retired: true, effectState: 'APPLIED', conversationKey,
    draftSha256: expectedDraftSha256,
    draftLength: Number.isInteger(retired.draftLength) ? retired.draftLength : null,
    retiredExecutionId: String(retired.retiredExecutionId || ''),
    supersededDeliveryId,
    composerEmpty: true,
    resumedDelivery: publicDeliveryReceipt(resumed),
  };
}

async function retireRecoveredExecution(message) {
  const id = deliveryId(message.deliveryId);
  const conversationKey = deliveryConversationKey(message.conversationKey);
  const expectedRequestSha256 = String(message.expectedRequestSha256 || '').trim().toLowerCase();
  const expectedResponseSha256 = String(message.expectedResponseSha256 || '').trim().toLowerCase();
  const expectedResponseLength = Number(message.expectedResponseLength);
  if (!/^[a-f0-9]{64}$/.test(expectedRequestSha256)
      || !/^[a-f0-9]{64}$/.test(expectedResponseSha256)
      || !Number.isInteger(expectedResponseLength) || expectedResponseLength <= 0) {
    return { ok: false, retired: false, effectState: 'NOT_APPLIED',
      error: 'DELIVERY_RECOVERED_RETIRE_ARGUMENT_INVALID' };
  }
  const ledger = await readDeliveryLedgerMirror();
  const receipt = ledger[id];
  if (!receipt || receipt.state !== 'NEEDS_REVIEW'
      || receipt.workerConversationKey !== conversationKey
      || receipt.requestSha256 !== expectedRequestSha256) {
    return { ok: false, retired: false, effectState: 'NOT_APPLIED',
      error: 'DELIVERY_RECOVERED_RETIRE_IDENTITY_INVALID' };
  }
  let workerTab;
  try { workerTab = singleDeliveryTab(await getChatTabs(), conversationKey); }
  catch (error) {
    return { ok: false, retired: false, effectState: 'NOT_APPLIED',
      error: String(error?.message || error).slice(0, 128) };
  }
  const retired = await sendToChatTab(workerTab.id, {
    type: 'relay:retireExecution', relayId: id, conversationKey,
    expectedRequestSha256, expectedResponseSha256, expectedResponseLength,
  });
  if (retired?.ok !== true || retired.retired !== true
      || retired.effectState !== 'APPLIED' || retired.relayId !== id
      || retired.conversationKey !== conversationKey
      || retired.requestSha256 !== expectedRequestSha256
      || retired.responseSha256 !== expectedResponseSha256
      || retired.responseLength !== expectedResponseLength
      || retired.executionAbsent !== true) {
    return { ok: false, retired: false,
      effectState: String(retired?.effectState || 'UNKNOWN'),
      error: String(retired?.error || 'DELIVERY_RECOVERED_RETIRE_ACK_INVALID').slice(0, 128) };
  }
  return { ok: true, retired: true, effectState: 'APPLIED', deliveryId: id,
    conversationKey, requestSha256: expectedRequestSha256,
    responseSha256: expectedResponseSha256, responseLength: expectedResponseLength,
    executionAbsent: true };
}

async function retireCapturedWorkerExecution(receipt) {
  if (receipt.workerExecutionRetired === true) return receipt;
  let workerTab;
  try {
    workerTab = singleDeliveryTab(await getChatTabs(), receipt.workerConversationKey);
    const retired = await sendToChatTab(workerTab.id, {
      type: 'relay:retireExecution', relayId: receipt.deliveryId,
      conversationKey: receipt.workerConversationKey,
      expectedRequestSha256: receipt.requestSubmittedSha256
        || await deliverySubmittedSha256(receipt.requestText),
      expectedResponseSha256: receipt.responseSha256,
      expectedResponseLength: receipt.responseLength,
    });
    if (retired?.ok !== true || retired.retired !== true) return receipt;
  } catch (_) {
    return receipt;
  }
  return writeDeliveryLedgerMirror(receipt.deliveryId, {
    ...receipt, workerExecutionRetired: true, updatedAt: Date.now(),
  });
}

async function deliveryStatus(message) {
  const id = deliveryId(message.deliveryId);
  const ledger = await readDeliveryLedgerMirror();
  let receipt = ledger[id];
  if (!receipt) return { ok: false, deliveryId: id, state: 'NEEDS_REVIEW',
    error: 'DELIVERY_MIRROR_NOT_FOUND' };
  if (receipt.state === 'REPLY_CAPTURED' && receipt.workerExecutionRetired !== true) {
    receipt = await retireCapturedWorkerExecution(receipt);
  }
  if (receipt.state === 'WAITING_TARGET') {
    return { ok: true, pending: true, ...publicDeliveryReceipt(receipt) };
  }
  if (receipt.state !== 'SENT_WAITING') {
    return { ok: !['NOT_APPLIED', 'NEEDS_REVIEW', 'FAILED'].includes(receipt.state),
      ...publicDeliveryReceipt(receipt) };
  }
  let workerTab;
  try {
    workerTab = singleDeliveryTab(await getChatTabs(), receipt.workerConversationKey);
  } catch (error) {
    return { ok: true, pending: true, ...publicDeliveryReceipt(receipt),
      error: String(error?.message || error).slice(0, 128) };
  }
  const read = await sendToChatTab(workerTab.id, {
    type: 'relay:simpleReadReply', conversationKey: receipt.workerConversationKey,
    afterAssistantCount: receipt.beforeAssistantCount, relayId: id,
  });
  if (read?.ok !== true || typeof read.responseText !== 'string' || !read.responseText) {
    // A not-yet-readable reply is observation latency, not a failed delivery.
    return { ok: true, pending: true, ...publicDeliveryReceipt(receipt),
      error: String(read?.error || 'DELIVERY_REPLY_PENDING').slice(0, 128) };
  }
  const captured = { ...receipt, state: 'REPLY_CAPTURED',
    responseText: read.responseText,
    responseSha256: await relaySha256(read.responseText),
    responseLength: read.responseText.length,
    workerTabId: workerTab.id, workerWindowId: workerTab.windowId,
    updatedAt: Date.now() };
  await writeDeliveryLedgerMirror(id, captured);
  const retired = await retireCapturedWorkerExecution(captured);
  return { ok: true, ...publicDeliveryReceipt(retired) };
}

async function deliveryReturn(message) {
  const id = deliveryId(message.deliveryId);
  const ledger = await readDeliveryLedgerMirror();
  const receipt = ledger[id];
  if (!receipt) return { ok: false, deliveryId: id, state: 'NEEDS_REVIEW',
    error: 'DELIVERY_MIRROR_NOT_FOUND' };
  if (receipt.state === 'RETURNED') return { ok: true, replayed: true,
    ...publicDeliveryReceipt(receipt) };
  if (receipt.state !== 'REPLY_CAPTURED' || !receipt.responseText) {
    return { ok: false, ...publicDeliveryReceipt(receipt),
      error: 'DELIVERY_REPLY_NOT_CAPTURED' };
  }
  let managerTab;
  try {
    managerTab = singleDeliveryTab(await getChatTabs(), receipt.managerConversationKey);
  } catch (error) {
    return { ok: false, ...publicDeliveryReceipt(receipt),
      error: String(error?.message || error).slice(0, 128) };
  }
  // The full current-turn Worker result is always included verbatim.
  // The BCT frame is computed before this submit and never authorized to
  // replace, omit, or truncate the captured Worker result.
  const header = message.managerReturnHeader;
  const footer = message.managerReturnFooter;
  const framed = typeof header === 'string' && typeof footer === 'string';
  if ((header !== undefined || footer !== undefined) && !framed) {
    return { ok: false, ...publicDeliveryReceipt(receipt),
      error: 'DELIVERY_MANAGER_FRAME_INVALID' };
  }
  if (framed && (!header.includes('[BCT_CURRENT_WORKER_RESULT_FULL]')
      || !footer.includes('[/BCT_CURRENT_WORKER_RESULT_FULL]'))) {
    return { ok: false, ...publicDeliveryReceipt(receipt),
      error: 'DELIVERY_MANAGER_FRAME_MARKERS_INVALID' };
  }
  const returnText = framed ? header + receipt.responseText + footer : receipt.responseText;
  if (returnText.length > 12000) {
    return { ok: false, ...publicDeliveryReceipt(receipt),
      error: 'DELIVERY_MANAGER_RETURN_TOO_LARGE' };
  }
  const returnHash = await relaySha256(returnText);
  if (receipt.managerReturnSha256 && receipt.managerReturnSha256 !== returnHash) {
    return { ok: false, ...publicDeliveryReceipt(receipt),
      error: 'DELIVERY_MANAGER_RETURN_HASH_CONFLICT' };
  }
  const intent = { ...receipt, managerReturnSha256: returnHash,
    managerReturnSubmittedSha256: await deliverySubmittedSha256(returnText),
    managerReturnLength: returnText.length,
    managerReturnSettingsSha256: String(message.managerReturnSettingsSha256 || ''),
    managerReturnText: returnText,
    updatedAt: Date.now() };
  await writeDeliveryLedgerMirror(id, intent);
  return attemptManagerReturn(intent, managerTab);
}

async function waitOrRejectManagerReturn(receipt, reason) {
  if (receipt.targetBusyPolicy === 'reject') {
    return writeDeliveryLedgerMirror(receipt.deliveryId, {
      ...receipt, managerReturnQueued: false, managerReturnWaitingReason: '',
      error: reason, updatedAt: Date.now(),
    });
  }
  return writeDeliveryLedgerMirror(receipt.deliveryId, {
    ...receipt, managerReturnQueued: true,
    managerReturnQueuedAt: Number(receipt.managerReturnQueuedAt || 0) || Date.now(),
    managerReturnWaitingReason: reason, error: '', updatedAt: Date.now(),
  });
}

async function attemptManagerReturn(receipt, managerTab) {
  let readiness;
  try {
    readiness = await inspectConversationReadiness(
      managerTab, receipt, receipt.managerConversationKey);
  } catch (error) {
    const queued = await waitOrRejectManagerReturn(receipt,
      'TARGET_READINESS_UNAVAILABLE:' + String(error?.message || error || 'unknown').slice(0, 80));
    return { ok: queued.managerReturnQueued === true, pending: queued.managerReturnQueued === true,
      ...publicDeliveryReceipt(queued) };
  }
  if (!readiness.ready) {
    const queued = await waitOrRejectManagerReturn(receipt, readiness.reason);
    return { ok: queued.managerReturnQueued === true, pending: queued.managerReturnQueued === true,
      ...publicDeliveryReceipt(queued) };
  }
  let ack;
  try {
    ack = await sendToChatTab(managerTab.id, {
      type: 'relay:simpleExecute', relayId: receipt.deliveryId,
      conversationKey: receipt.managerConversationKey, text: receipt.managerReturnText,
      composerWakeMode: receipt.composerWakeMode,
      sendButtonWaitMs: receipt.sendButtonWaitMs,
    });
  } catch (error) {
    const unresolved = { ...receipt, state: 'NEEDS_REVIEW', updatedAt: Date.now(),
      managerReturnQueued: false, managerReturnWaitingReason: '',
      error: String(error?.message || error || 'DELIVERY_RETURN_UNKNOWN').slice(0, 128) };
    await writeDeliveryLedgerMirror(receipt.deliveryId, unresolved);
    return { ok: false, ...publicDeliveryReceipt(unresolved) };
  }
  if (ack?.ok === true && ack.submitted === true
      && ack.conversationKey === receipt.managerConversationKey) {
    const returned = { ...receipt, state: 'RETURNED',
      managerTabId: managerTab.id, managerWindowId: managerTab.windowId,
      managerReturnQueued: false, managerReturnWaitingReason: '', managerReturnText: '',
      managerBeforeAssistantCount: Number.isInteger(ack.beforeAssistantCount)
        ? ack.beforeAssistantCount : null,
      updatedAt: Date.now() };
    await writeDeliveryLedgerMirror(receipt.deliveryId, returned);
    return { ok: true, ...publicDeliveryReceipt(returned) };
  }
  // An explicit pre-submit rejection leaves the captured reply returnable by
  // a later operation with the same delivery id.  It does not fail the worker
  // turn and does not authorize a new delivery id.
  const error = String(ack?.error || 'DELIVERY_RETURN_ACK_INVALID').slice(0, 128);
  if (ack?.effectState === 'NOT_APPLIED' && DELIVERY_WAITABLE_ERRORS.has(error)) {
    const queued = await waitOrRejectManagerReturn(receipt, error);
    return { ok: queued.managerReturnQueued === true, pending: queued.managerReturnQueued === true,
      ...publicDeliveryReceipt(queued) };
  }
  const state = ack?.effectState === 'NOT_APPLIED' ? 'REPLY_CAPTURED' : 'NEEDS_REVIEW';
  const unresolved = { ...receipt, state, updatedAt: Date.now(),
    managerReturnQueued: false, managerReturnWaitingReason: '', error };
  await writeDeliveryLedgerMirror(receipt.deliveryId, unresolved);
  if (state === 'NEEDS_REVIEW') {
    const reconciled = await reconcileManagerReturnEffect(unresolved, managerTab);
    if (reconciled.state === 'RETURNED') {
      return { ok: true, reconciled: true, ...publicDeliveryReceipt(reconciled) };
    }
  }
  return { ok: false, ...publicDeliveryReceipt(unresolved) };
}

async function reconcileManagerReturnEffect(receipt, suppliedManagerTab = null) {
  const submittedSha256 = String(receipt?.managerReturnSubmittedSha256 || '');
  const unknownReturn = receipt?.state === 'NEEDS_REVIEW' && !!receipt.managerReturnText;
  const returnedWithoutProof = receipt?.state === 'RETURNED'
    && receipt.managerReturnReconciled !== true;
  if (!receipt || (!unknownReturn && !returnedWithoutProof)
      || !/^[a-f0-9]{64}$/.test(submittedSha256)) {
    return receipt;
  }
  let managerTab = suppliedManagerTab;
  try {
    managerTab = managerTab || singleDeliveryTab(
      await getChatTabs(), receipt.managerConversationKey);
  } catch (_) {
    return receipt;
  }
  let proof;
  try {
    proof = await sendToChatTab(managerTab.id, {
      type: 'relay:exactUserTurnProof', deliveryId: receipt.deliveryId,
      conversationKey: receipt.managerConversationKey,
      text: receipt.managerReturnText || '',
      submittedSha256,
    });
  } catch (_) {
    return receipt;
  }
  if (proof?.ok !== true || proof.deliveryId !== receipt.deliveryId
      || proof.conversationKey !== receipt.managerConversationKey
      || proof.submittedSha256 !== receipt.managerReturnSubmittedSha256
      || !String(proof.turnKey || '')
      || !Number.isInteger(proof.beforeAssistantCount)
      || proof.beforeAssistantCount < 0) {
    return receipt;
  }
  return writeDeliveryLedgerMirror(receipt.deliveryId, {
    ...receipt, state: 'RETURNED', managerTabId: managerTab.id,
    managerWindowId: managerTab.windowId,
    managerBeforeAssistantCount: proof.beforeAssistantCount,
    managerReturnTurnKey: String(proof.turnKey),
    managerReturnReconciled: true, managerReturnQueued: false,
    managerReturnWaitingReason: '', managerReturnText: '', error: '',
    updatedAt: Date.now(),
  });
}

async function resumeQueuedManagerReturn(deliveryIdValue) {
  const id = deliveryId(deliveryIdValue);
  if (deliveryResumeLocks.has(id)) return deliveryResumeLocks.get(id);
  const operation = (async () => {
    const ledger = await readDeliveryLedgerMirror();
    const receipt = ledger[id];
    if (!receipt || receipt.state !== 'REPLY_CAPTURED'
        || receipt.managerReturnQueued !== true || !receipt.managerReturnText) {
      return receipt || null;
    }
    let managerTab;
    try { managerTab = singleDeliveryTab(await getChatTabs(), receipt.managerConversationKey); }
    catch (_) { return waitOrRejectManagerReturn(receipt, 'TARGET_TAB_NOT_UNIQUELY_OPEN'); }
    return attemptManagerReturn(receipt, managerTab);
  })().finally(() => deliveryResumeLocks.delete(id));
  deliveryResumeLocks.set(id, operation);
  return operation;
}


async function retireCapturedManagerExecution(receipt) {
  if (receipt.managerExecutionRetired === true) return receipt;
  let managerTab;
  try {
    managerTab = singleDeliveryTab(await getChatTabs(), receipt.managerConversationKey);
    const retireMessage = {
      type: 'relay:retireExecution', relayId: receipt.deliveryId,
      conversationKey: receipt.managerConversationKey,
      expectedRequestSha256: receipt.managerReturnSubmittedSha256
        || receipt.managerReturnSha256,
      expectedResponseSha256: receipt.managerResponseSha256,
      expectedResponseLength: receipt.managerResponseLength,
    };
    let retired = await sendToChatTab(managerTab.id, retireMessage);
    // Receipts created before submitted-text identity was persisted contain
    // only the pre-normalization return hash.  The content script stores the
    // exact normalized text it actually submitted and returns that hash on an
    // explicit identity mismatch.  Adopt it only for this legacy shape and
    // retry retirement once; the relay id, conversation and captured response
    // identity are still independently checked by relay:retireExecution.
    const legacySubmittedSha256 = String(retired?.requestSha256 || '').trim().toLowerCase();
    if (!receipt.managerReturnSubmittedSha256
        && retired?.effectState === 'NOT_APPLIED'
        && retired?.error === 'RELAY_RETIRE_REQUEST_IDENTITY_MISMATCH'
        && /^[a-f0-9]{64}$/.test(legacySubmittedSha256)) {
      retired = await sendToChatTab(managerTab.id, {
        ...retireMessage, expectedRequestSha256: legacySubmittedSha256,
      });
      if (retired?.ok === true && retired.retired === true) {
        receipt = { ...receipt, managerReturnSubmittedSha256: legacySubmittedSha256 };
      }
    }
    if (retired?.ok !== true || retired.retired !== true) return receipt;
  } catch (_) {
    return receipt;
  }
  return writeDeliveryLedgerMirror(receipt.deliveryId, {
    ...receipt, managerExecutionRetired: true, updatedAt: Date.now(),
  });
}


// Read the Manager's new completed reply for the exact return turn. This is a
// read-only continuation of the same delivery, never a second message submit.
async function deliveryManagerStatus(message) {
  const id = deliveryId(message.deliveryId);
  const ledger = await readDeliveryLedgerMirror();
  let receipt = ledger[id];
  if (!receipt) return { ok: false, deliveryId: id, state: 'NEEDS_REVIEW',
    error: 'DELIVERY_MIRROR_NOT_FOUND' };
  if (receipt.state === 'NEEDS_REVIEW'
      || (receipt.state === 'RETURNED' && receipt.managerReturnReconciled !== true)) {
    receipt = await reconcileManagerReturnEffect(receipt);
  }
  if (receipt.state !== 'RETURNED') {
    return { ok: true, pending: true, ...publicDeliveryReceipt(receipt) };
  }
  const reconciled = receipt.managerReturnReconciled === true;
  if (!Number.isInteger(receipt.managerBeforeAssistantCount)) {
    return { ok: false, reconciled, ...publicDeliveryReceipt(receipt),
      error: 'DELIVERY_MANAGER_BASELINE_NOT_CAPTURED' };
  }
  let managerTab;
  try {
    managerTab = singleDeliveryTab(await getChatTabs(), receipt.managerConversationKey);
  } catch (error) {
    return { ok: true, pending: true, reconciled, ...publicDeliveryReceipt(receipt),
      error: String(error?.message || error).slice(0, 128) };
  }
  let read;
  try {
    read = await sendToChatTab(managerTab.id, {
      type: 'relay:simpleReadReply', conversationKey: receipt.managerConversationKey,
      afterAssistantCount: receipt.managerBeforeAssistantCount, relayId: id,
    });
  } catch (error) {
    return { ok: true, pending: true, reconciled, ...publicDeliveryReceipt(receipt),
      error: String(error?.message || error).slice(0, 128) };
  }
  if (read?.ok !== true || read.conversationKey !== receipt.managerConversationKey
      || typeof read.responseText !== 'string' || !read.responseText) {
    return { ok: true, pending: true, reconciled, ...publicDeliveryReceipt(receipt),
      error: String(read?.error || 'DELIVERY_MANAGER_REPLY_PENDING').slice(0, 128) };
  }
  if (read.responseText.length > 12000) {
    return { ok: false, reconciled, ...publicDeliveryReceipt(receipt),
      error: 'DELIVERY_MANAGER_REPLY_TOO_LARGE' };
  }
  const hash = await relaySha256(read.responseText);
  if (receipt.managerResponseSha256 && receipt.managerResponseSha256 !== hash) {
    return { ok: false, reconciled, ...publicDeliveryReceipt(receipt),
      error: 'DELIVERY_MANAGER_REPLY_CHANGED' };
  }
  const observed = { ...receipt, managerResponseSha256: hash,
    managerResponseLength: read.responseText.length, updatedAt: Date.now() };
  await writeDeliveryLedgerMirror(id, observed);
  receipt = await retireCapturedManagerExecution(observed);
  return { ok: true, reconciled,
    ...publicDeliveryReceipt(receipt),
    managerResponseText: read.responseText };
}

 // Observe one exact historical original effect without writing the Delivery
 // mirror. The normal return route MUST remain closed for NEEDS_REVIEW.
async function deliveryRecoveryInspect(message) {
  const id = deliveryId(message.deliveryId);
  const managerKey = deliveryConversationKey(message.managerConversationKey);
  const workerKey = deliveryConversationKey(message.workerConversationKey);
  const expectedSha = String(message.requestSha256 || '');
  const ledger = await readDeliveryLedgerMirror();
  const original = ledger[id];
  if (!original || original.state !== 'NEEDS_REVIEW'
      || original.managerConversationKey !== managerKey
      || original.workerConversationKey !== workerKey
      || original.requestSha256 !== expectedSha) {
    return { ok: false, deliveryId: id, state: 'NEEDS_REVIEW',
      error: 'DELIVERY_RECOVERY_ORIGINAL_MIRROR_MISMATCH' };
  }
  const fingerprint = await relaySha256(JSON.stringify([id, managerKey, workerKey, expectedSha]));
  if (original.fingerprint !== fingerprint) {
    return { ok: false, deliveryId: id, state: 'NEEDS_REVIEW',
      error: 'DELIVERY_RECOVERY_FINGERPRINT_MISMATCH' };
  }
  let tabs;
  try {
    tabs = deliveryTabs(await getChatTabs(), managerKey, workerKey);
  } catch (error) {
    return { ok: false, deliveryId: id, state: 'NEEDS_REVIEW',
      error: String(error?.message || error).slice(0, 128) };
  }
  const observed = await sendToChatTab(tabs.worker.id, {
    type: 'relay:deliveryRecoveryProof', deliveryId: id,
    conversationKey: workerKey, requestSha256: expectedSha
  });
  if (observed?.ok !== true || observed.deliveryId !== id
      || observed.conversationKey !== workerKey
      || observed.requestSha256 !== expectedSha
      || !String(observed.turnKey || '')
      || !['submit-activated','submitted','completed'].includes(String(observed.phase || ''))
      || typeof observed.responseText !== 'string' || !observed.responseText
      || observed.responseText.length > 12000
      || observed.responseSha256 !== await relaySha256(observed.responseText)
      || observed.responseLength !== observed.responseText.length) {
    return { ok: false, deliveryId: id, state: 'NEEDS_REVIEW',
      error: String(observed?.error || 'DELIVERY_RECOVERY_PROOF_INVALID').slice(0, 128) };
  }
  return {
    ok: true, deliveryId: id, state: 'NEEDS_REVIEW', reconciled: false,
    managerConversationKey: managerKey, workerConversationKey: workerKey,
    requestSha256: expectedSha, workerTabId: tabs.worker.id,
    workerWindowId: tabs.worker.windowId, managerTabId: tabs.manager.id,
    managerWindowId: tabs.manager.windowId, originalTurnKey: observed.turnKey,
    recordPhase: observed.phase, responseText: observed.responseText,
    responseSha256: observed.responseSha256, responseLength: observed.responseLength
  };
}
