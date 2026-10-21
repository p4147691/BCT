const DELIVERY_LEDGER_MIRROR_KEY = 'deliveryLedgerMirrorV1';

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

async function readDeliveryLedgerMirror() {
  const data = await stateRepository.getLocal(DELIVERY_LEDGER_MIRROR_KEY);
  const value = data[DELIVERY_LEDGER_MIRROR_KEY];
  return value && typeof value === 'object' ? value : {};
}

async function writeDeliveryLedgerMirror(id, receipt) {
  const ledger = await readDeliveryLedgerMirror();
  ledger[id] = receipt;
  const entries = Object.entries(ledger)
    .sort((a, b) => Number(b[1]?.updatedAt || 0) - Number(a[1]?.updatedAt || 0));
  const activeStates = new Set(['NOT_SENT', 'SENT_WAITING', 'REPLY_CAPTURED']);
  // Never evict a delivery that still owns the only reply text or duplicate
  // submission fence. Bound only terminal audit mirrors; BCT owns durable
  // history for those terminal rows.
  const active = entries.filter(([, value]) => activeStates.has(value?.state));
  const terminal = entries.filter(([, value]) => !activeStates.has(value?.state)).slice(0, 64);
  const keep = [...active, ...terminal];
  await stateRepository.setLocal({ [DELIVERY_LEDGER_MIRROR_KEY]: Object.fromEntries(keep) });
  return receipt;
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

function publicDeliveryReceipt(receipt) {
  if (!receipt || typeof receipt !== 'object') return null;
  return {
    deliveryId: String(receipt.deliveryId || ''),
    state: String(receipt.state || ''),
    managerConversationKey: String(receipt.managerConversationKey || ''),
    workerConversationKey: String(receipt.workerConversationKey || ''),
    requestSha256: String(receipt.requestSha256 || ''),
    responseSha256: String(receipt.responseSha256 || ''),
    responseLength: Number.isInteger(receipt.responseLength) ? receipt.responseLength : null,
    workerTabId: Number.isInteger(receipt.workerTabId) ? receipt.workerTabId : null,
    workerWindowId: Number.isInteger(receipt.workerWindowId) ? receipt.workerWindowId : null,
    managerTabId: Number.isInteger(receipt.managerTabId) ? receipt.managerTabId : null,
    managerWindowId: Number.isInteger(receipt.managerWindowId) ? receipt.managerWindowId : null,
    error: String(receipt.error || ''),
  };
}

async function deliveryStart(message) {
  const id = deliveryId(message.deliveryId);
  const managerConversationKey = deliveryConversationKey(message.managerConversationKey);
  const workerConversationKey = deliveryConversationKey(message.workerConversationKey);
  const text = String(message.text || '');
  const requestSha256 = String(message.requestSha256 || '').trim();
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
  const intent = {
    version: 1, deliveryId: id, fingerprint, managerConversationKey,
    workerConversationKey, requestSha256, state: 'NOT_SENT', updatedAt: Date.now(),
  };
  await writeDeliveryLedgerMirror(id, intent);
  let ack;
  try {
    ack = await sendToChatTab(tabs.worker.id, {
      type: 'relay:simpleExecute', relayId: id,
      conversationKey: workerConversationKey, text,
    });
  } catch (error) {
    const receipt = { ...intent, state: 'NEEDS_REVIEW', updatedAt: Date.now(),
      error: String(error?.message || error || 'DELIVERY_TRANSPORT_UNKNOWN').slice(0, 128) };
    await writeDeliveryLedgerMirror(id, receipt);
    return { ok: false, ...publicDeliveryReceipt(receipt) };
  }
  if (ack?.ok === true && ack.submitted === true
      && ack.conversationKey === workerConversationKey) {
    const receipt = { ...intent, state: 'SENT_WAITING',
      beforeAssistantCount: Number(ack.beforeAssistantCount || 0),
      workerTabId: tabs.worker.id, workerWindowId: tabs.worker.windowId,
      updatedAt: Date.now() };
    await writeDeliveryLedgerMirror(id, receipt);
    return { ok: true, ...publicDeliveryReceipt(receipt) };
  }
  const state = ack?.effectState === 'NOT_APPLIED' ? 'NOT_APPLIED' : 'NEEDS_REVIEW';
  const receipt = { ...intent, state, updatedAt: Date.now(),
    error: String(ack?.error || 'DELIVERY_ACK_INVALID').slice(0, 128) };
  await writeDeliveryLedgerMirror(id, receipt);
  return { ok: false, ...publicDeliveryReceipt(receipt) };
}

async function deliveryStatus(message) {
  const id = deliveryId(message.deliveryId);
  const ledger = await readDeliveryLedgerMirror();
  const receipt = ledger[id];
  if (!receipt) return { ok: false, deliveryId: id, state: 'NEEDS_REVIEW',
    error: 'DELIVERY_MIRROR_NOT_FOUND' };
  if (receipt.state !== 'SENT_WAITING') {
    return { ok: !['NOT_APPLIED', 'NEEDS_REVIEW', 'FAILED'].includes(receipt.state),
      ...publicDeliveryReceipt(receipt) };
  }
  let tabs;
  try {
    tabs = deliveryTabs(await getChatTabs(), receipt.managerConversationKey,
      receipt.workerConversationKey);
  } catch (error) {
    return { ok: true, pending: true, ...publicDeliveryReceipt(receipt),
      error: String(error?.message || error).slice(0, 128) };
  }
  const read = await sendToChatTab(tabs.worker.id, {
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
    workerTabId: tabs.worker.id, workerWindowId: tabs.worker.windowId,
    updatedAt: Date.now() };
  await writeDeliveryLedgerMirror(id, captured);
  return { ok: true, ...publicDeliveryReceipt(captured) };
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
  let tabs;
  try {
    tabs = deliveryTabs(await getChatTabs(), receipt.managerConversationKey,
      receipt.workerConversationKey);
  } catch (error) {
    return { ok: false, ...publicDeliveryReceipt(receipt),
      error: String(error?.message || error).slice(0, 128) };
  }
  let ack;
  try {
    ack = await sendToChatTab(tabs.manager.id, {
      type: 'relay:simpleExecute', relayId: id,
      conversationKey: receipt.managerConversationKey, text: receipt.responseText,
    });
  } catch (error) {
    const unresolved = { ...receipt, state: 'NEEDS_REVIEW', updatedAt: Date.now(),
      error: String(error?.message || error || 'DELIVERY_RETURN_UNKNOWN').slice(0, 128) };
    await writeDeliveryLedgerMirror(id, unresolved);
    return { ok: false, ...publicDeliveryReceipt(unresolved) };
  }
  if (ack?.ok === true && ack.submitted === true
      && ack.conversationKey === receipt.managerConversationKey) {
    const returned = { ...receipt, state: 'RETURNED', responseText: undefined,
      managerTabId: tabs.manager.id, managerWindowId: tabs.manager.windowId,
      updatedAt: Date.now() };
    await writeDeliveryLedgerMirror(id, returned);
    return { ok: true, ...publicDeliveryReceipt(returned) };
  }
  // An explicit pre-submit rejection leaves the captured reply returnable by
  // a later operation with the same delivery id.  It does not fail the worker
  // turn and does not authorize a new delivery id.
  const state = ack?.effectState === 'NOT_APPLIED' ? 'REPLY_CAPTURED' : 'NEEDS_REVIEW';
  const unresolved = { ...receipt, state, updatedAt: Date.now(),
    error: String(ack?.error || 'DELIVERY_RETURN_ACK_INVALID').slice(0, 128) };
  await writeDeliveryLedgerMirror(id, unresolved);
  return { ok: false, ...publicDeliveryReceipt(unresolved) };
}
