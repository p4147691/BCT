async function relaySha256(value) {
  const bytes = new TextEncoder().encode(String(value));
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, '0')).join('');
}

function publicResultFromReceipt(receipt) {
  if (!receipt) return null;
  const payload = receipt.resultPayload || {};
  return {
    id: String(receipt.routeId || ''),
    from: String(receipt.to || ''),
    ok: payload.ok === true,
    reply: String(payload.reply || ''),
    replyLength: String(payload.reply || '').length,
    error: String(payload.error || ''),
    failureEvidence: payload.failureEvidence || null,
    ambiguous: payload.ambiguous === true,
    fingerprint: String(receipt.dispatchFingerprint || ''),

    messageHash: String(receipt.messageHash || ''),
    targetBindingReceipt: String(receipt.targetBindingReceipt || ''),
    instanceId: String(receipt.instanceId || ''),
    sessionId: String(receipt.sessionId || ''),
    attachmentGeneration: Number(receipt.attachmentGeneration) || null,
    bindingLeaseId: String(receipt.bindingLeaseId || ''),
    bindingLeaseConsumedAt: Number(receipt.bindingLeaseConsumedAt) || null,
    tabId: Number(receipt.tabId) || null,
    conversationKey: String(receipt.conversationKey || ''),
    resultHash: String(receipt.resultHash || ''),
    submitState: String(receipt.submitState || ''),
    resultState: String(receipt.resultState || ''),
    ackState: String(receipt.ackState || ''),
    receiverAckState: String(receipt.receiverAckState || ''),
    returnState: String(receipt.returnState || ''),
    stageTiming: receipt.stageTiming || null,
    timing: receipt.timing || null,
    at: Number(receipt.completedAt || 0) || null
  };
}

// A completed worker result is durable before it ever reaches the manager.  If
// the manager is composing or generating, keep that result pending and retry
// only after the *same exact tab* reports that its composer is empty again.
// This is deliberately event-driven: it does not poll ChatGPT, overwrite a
// user draft, or redirect a result to a different role/tab.
async function readSimpleRelayV0Receipts() {
  const data = await stateRepository.getLocal(SIMPLE_RELAY_V0_RECEIPTS_KEY);
  const receipts = data[SIMPLE_RELAY_V0_RECEIPTS_KEY];
  return receipts && typeof receipts === 'object' ? receipts : {};
}

async function writeSimpleRelayV0Receipt(operationId, receipt) {
  const receipts = await readSimpleRelayV0Receipts();
  receipts[operationId] = receipt;
  const keep = Object.entries(receipts)
    .sort((a, b) => Number(b[1]?.updatedAt || 0) - Number(a[1]?.updatedAt || 0))
    .slice(0, 32);
  await stateRepository.setLocal({ [SIMPLE_RELAY_V0_RECEIPTS_KEY]: Object.fromEntries(keep) });
}

function publicSimpleRelayV0Receipt(receipt) {
  if (!receipt || typeof receipt !== 'object') return null;
  return {
    operationId: String(receipt.operationId || ''),
    sourceOperationId: String(receipt.sourceOperationId || ''),
    kind: String(receipt.kind || 'DELIVERY'),
    state: String(receipt.state || ''),
    targetConversationKey: String(receipt.targetConversationKey || ''),
    responseLength: Number.isInteger(receipt.responseLength) ? receipt.responseLength : null,
    error: String(receipt.error || ''),
  };
}

