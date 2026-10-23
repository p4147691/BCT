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
    managerReturnLength: returnText.length,
    managerReturnSettingsSha256: String(message.managerReturnSettingsSha256 || ''),
    updatedAt: Date.now() };
  await writeDeliveryLedgerMirror(id, intent);
  let ack;
  try {
    ack = await sendToChatTab(managerTab.id, {
      type: 'relay:simpleExecute', relayId: id,
      conversationKey: receipt.managerConversationKey, text: returnText,
    });
  } catch (error) {
    const unresolved = { ...intent, state: 'NEEDS_REVIEW', updatedAt: Date.now(),
      error: String(error?.message || error || 'DELIVERY_RETURN_UNKNOWN').slice(0, 128) };
    await writeDeliveryLedgerMirror(id, unresolved);
    return { ok: false, ...publicDeliveryReceipt(unresolved) };
  }
  if (ack?.ok === true && ack.submitted === true
      && ack.conversationKey === receipt.managerConversationKey) {
    const returned = { ...intent, state: 'RETURNED',
      managerTabId: managerTab.id, managerWindowId: managerTab.windowId,
      managerBeforeAssistantCount: Number.isInteger(ack.beforeAssistantCount)
        ? ack.beforeAssistantCount : null,
      updatedAt: Date.now() };
    await writeDeliveryLedgerMirror(id, returned);
    return { ok: true, ...publicDeliveryReceipt(returned) };
  }
  // An explicit pre-submit rejection leaves the captured reply returnable by
  // a later operation with the same delivery id.  It does not fail the worker
  // turn and does not authorize a new delivery id.
  const state = ack?.effectState === 'NOT_APPLIED' ? 'REPLY_CAPTURED' : 'NEEDS_REVIEW';
  const unresolved = { ...intent, state, updatedAt: Date.now(),
    error: String(ack?.error || 'DELIVERY_RETURN_ACK_INVALID').slice(0, 128) };
  await writeDeliveryLedgerMirror(id, unresolved);
  return { ok: false, ...publicDeliveryReceipt(unresolved) };
}


// Read the Manager's new completed reply for the exact return turn. This is a
// read-only continuation of the same delivery, never a second message submit.
async function deliveryManagerStatus(message) {
  const id = deliveryId(message.deliveryId);
  const ledger = await readDeliveryLedgerMirror();
  const receipt = ledger[id];
  if (!receipt) return { ok: false, deliveryId: id, state: 'NEEDS_REVIEW',
    error: 'DELIVERY_MIRROR_NOT_FOUND' };
  if (receipt.state !== 'RETURNED') {
    return { ok: true, pending: true, ...publicDeliveryReceipt(receipt) };
  }
  if (!Number.isInteger(receipt.managerBeforeAssistantCount)) {
    return { ok: false, ...publicDeliveryReceipt(receipt),
      error: 'DELIVERY_MANAGER_BASELINE_NOT_CAPTURED' };
  }
  let managerTab;
  try {
    managerTab = singleDeliveryTab(await getChatTabs(), receipt.managerConversationKey);
  } catch (error) {
    return { ok: true, pending: true, ...publicDeliveryReceipt(receipt),
      error: String(error?.message || error).slice(0, 128) };
  }
  let read;
  try {
    read = await sendToChatTab(managerTab.id, {
      type: 'relay:simpleReadReply', conversationKey: receipt.managerConversationKey,
      afterAssistantCount: receipt.managerBeforeAssistantCount, relayId: id,
    });
  } catch (error) {
    return { ok: true, pending: true, ...publicDeliveryReceipt(receipt),
      error: String(error?.message || error).slice(0, 128) };
  }
  if (read?.ok !== true || read.conversationKey !== receipt.managerConversationKey
      || typeof read.responseText !== 'string' || !read.responseText) {
    return { ok: true, pending: true, ...publicDeliveryReceipt(receipt),
      error: String(read?.error || 'DELIVERY_MANAGER_REPLY_PENDING').slice(0, 128) };
  }
  if (read.responseText.length > 12000) {
    return { ok: false, ...publicDeliveryReceipt(receipt),
      error: 'DELIVERY_MANAGER_REPLY_TOO_LARGE' };
  }
  const hash = await relaySha256(read.responseText);
  if (receipt.managerResponseSha256 && receipt.managerResponseSha256 !== hash) {
    return { ok: false, ...publicDeliveryReceipt(receipt),
      error: 'DELIVERY_MANAGER_REPLY_CHANGED' };
  }
  const observed = { ...receipt, managerResponseSha256: hash,
    managerResponseLength: read.responseText.length, updatedAt: Date.now() };
  await writeDeliveryLedgerMirror(id, observed);
  return { ok: true, ...publicDeliveryReceipt(observed),
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
