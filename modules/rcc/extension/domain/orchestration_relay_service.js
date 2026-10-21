let orchestrationRelayReceiptMutation = Promise.resolve();
const orchestrationRelayInflight = new Map();

function orchestrationRelayBinding(expected, actual) {
  if (!expected || !actual) return false;
  return String(actual.instanceId || actual.transportInstanceId || '') === String(expected.instanceId || '')
    && String(actual.sessionId || '') === String(expected.sessionId || '')
    && Number(actual.tabId || 0) === Number(expected.tabId || 0)
    && String(actual.conversationKey || '') === String(expected.conversationKey || '')
    && String(actual.bindingReceiptId || '') === String(expected.bindingReceiptId || '')
    && Number(actual.attachmentGeneration || 0) === Number(expected.attachmentGeneration || 0);
}

function orchestrationRelayExpected(message) {
  return {
    instanceId: String(message?.expectedInstanceId || ''),
    sessionId: String(message?.expectedSessionId || ''),
    tabId: Number(message?.expectedTabId || 0),
    conversationKey: String(message?.expectedConversationKey || '').trim(),
    bindingReceiptId: String(message?.bindingReceiptId || '').trim(),
    attachmentGeneration: Number(message?.attachmentGeneration || 0),
  };
}

function orchestrationRelayFingerprint(role, text, expected, messageHash) {
  return JSON.stringify([
    role, text, false, '', expected.bindingReceiptId, String(messageHash || ''),
    expected.instanceId, expected.sessionId, expected.tabId,
    expected.conversationKey, expected.attachmentGeneration,
  ]);
}

async function resolveOrchestrationRelayTarget(message) {
  await endpointSessionReady;
  const role = RelayCore.normalizeRole(message?.to);
  const expected = orchestrationRelayExpected(message);
  if (!role || !/^[a-f0-9]{64}$/i.test(String(message?.messageHash || ''))
      || !/^RCB-[A-Z0-9]{12,40}$/.test(expected.bindingReceiptId)
      || !expected.instanceId || !expected.sessionId
      || !Number.isSafeInteger(expected.tabId) || expected.tabId <= 0
      || !/^[a-z0-9-]{8,64}$/i.test(expected.conversationKey)
      || !Number.isSafeInteger(expected.attachmentGeneration)
      || expected.attachmentGeneration <= 0) {
    throw new Error('ORCHESTRATION_RELAY_EXACT_BINDING_REQUIRED');
  }
  const state = await loadState();
  if (expected.instanceId !== String(state.settings?.instanceId || '')
      || expected.sessionId !== String(endpointSessionId || '')) {
    throw new Error('ORCHESTRATION_RELAY_SESSION_MISMATCH');
  }
  const registration = state.registrations?.[role] || null;
  if (!registration || !orchestrationRelayBinding(expected, {
    ...registration,
    attachmentGeneration: expected.attachmentGeneration,
  })) {
    throw new Error('ORCHESTRATION_RELAY_BINDING_MISMATCH');
  }
  const tab = await browserGateway.getExactTab(expected.tabId);
  if (!isChatTab(tab)
      || RelayCore.conversationKey(String(tab.url || '')) !== expected.conversationKey) {
    throw new Error('ORCHESTRATION_RELAY_TARGET_MISMATCH');
  }
  return { role, expected, state, registration, tab };
}

async function sendOrchestrationRelay(message, requestId) {
  const relayId = String(requestId || '').trim();
  const text = String(message?.text || '');
  if (!relayId || !text || text.length > 12000) {
    throw new Error('ORCHESTRATION_RELAY_ARGUMENT_INVALID');
  }
  const target = await resolveOrchestrationRelayTarget(message);
  const fingerprint = orchestrationRelayFingerprint(
    target.role, text, target.expected, message.messageHash,
  );
  const running = orchestrationRelayInflight.get(relayId);
  if (running) {
    if (running.fingerprint !== fingerprint) throw new Error('RELAY_ID_REUSE_MISMATCH');
    return { ...(await running.promise), duplicate: true, inflight: true };
  }
  const promise = (async () => {
    const fresh = await loadState();
    const completed = publicResultFromReceipt(fresh.resultReceipts?.[relayId]);
    if (completed) {
      if (completed.fingerprint !== fingerprint) throw new Error('RELAY_ID_REUSE_MISMATCH');
      return { ok: true, relayId, completed: true, completedResult: completed, duplicate: true };
    }
    const existing = fresh.pending?.[relayId] || null;
    if (existing) {
      if (String(existing.fingerprint || '') !== fingerprint) throw new Error('RELAY_ID_REUSE_MISMATCH');
      return { ok: true, relayId, pending: true, duplicate: true,
        submitted: existing.deliveryConfirmed === true };
    }
    const pending = {
      kind: 'ORCHESTRATION_RELAY_V1', to: target.role, tabId: target.expected.tabId,
      conversationKey: target.expected.conversationKey, source: 'BCT_ORCHESTRATION',
      fromNode: String(message?.fromNode || ''), messageHash: String(message?.messageHash || ''),
      targetBindingReceipt: target.expected.bindingReceiptId,
      expectedInstanceId: target.expected.instanceId,
      expectedSessionId: target.expected.sessionId,
      attachmentGeneration: target.expected.attachmentGeneration,
      fingerprint, createdAt: Date.now(), deliveryConfirmed: false,
    };
    fresh.pending[relayId] = pending;
    await stateRepository.setLocal({ pending: fresh.pending });
    let ack;
    try {
      ack = await sendToChatTab(target.expected.tabId, {
        type: 'relay:orchestrationExecute', relayId, text,
        exactBinding: { ...target.expected },
      });
    } catch (error) {
      const uncertain = await loadState();
      if (uncertain.pending?.[relayId]) {
        uncertain.pending[relayId].submitUnknown = true;
        uncertain.pending[relayId].lastTransportError = String(error?.message || error).slice(0, 200);
        await stateRepository.setLocal({ pending: uncertain.pending });
      }
      throw error;
    }
    if (ack?.ok !== true || ack?.submitted !== true) {
      const latest = await loadState();
      const notApplied = ack?.effectState === 'NOT_APPLIED' && ack?.submitted === false;
      if (notApplied) delete latest.pending[relayId];
      else if (latest.pending?.[relayId]) latest.pending[relayId].submitUnknown = true;
      await stateRepository.setLocal({ pending: latest.pending });
      return { ok: false, relayId, effectState: notApplied ? 'NOT_APPLIED' : 'UNKNOWN',
        ambiguous: !notApplied, error: String(ack?.error || 'ORCHESTRATION_RELAY_ACK_INVALID') };
    }
    const latest = await loadState();
    const stored = latest.pending?.[relayId];
    if (!stored) throw new Error('ORCHESTRATION_RELAY_PENDING_LOST');
    if (!orchestrationRelayBinding(target.expected, ack.bindingAttestation)) {
      stored.submitUnknown = true;
      stored.lastTransportError = 'ORCHESTRATION_RELAY_ACK_BINDING_MISMATCH';
      latest.pending[relayId] = stored;
      await stateRepository.setLocal({ pending: latest.pending });
      throw new Error('ORCHESTRATION_RELAY_ACK_BINDING_MISMATCH');
    }
    stored.deliveryConfirmed = true;
    stored.submittedAt = Date.now();
    stored.bindingAttestation = { ...ack.bindingAttestation };
    latest.pending[relayId] = stored;
    await stateRepository.setLocal({ pending: latest.pending });
    return { ok: true, relayId, submitted: true };
  })();
  orchestrationRelayInflight.set(relayId, { fingerprint, promise });
  try { return await promise; }
  finally { orchestrationRelayInflight.delete(relayId); }
}

async function authorizeOrchestrationRelay(message, sender) {
  await endpointSessionReady;
  if (lifecycle.runtimeSenderKind(sender) !== 'CHAT_CONTENT'
      || Number(sender?.frameId || 0) !== 0 || !isChatTab(sender?.tab)) {
    throw new Error('ORCHESTRATION_RELAY_SENDER_REJECTED');
  }
  const relayId = String(message?.relayId || '').trim();
  const expected = message?.exactBinding && typeof message.exactBinding === 'object'
    ? { ...message.exactBinding } : null;
  const state = await loadState();
  const pending = state.pending?.[relayId] || null;
  const role = String(pending?.to || '');
  const registration = state.registrations?.[role] || null;
  const live = {
    instanceId: String(state.settings?.instanceId || ''),
    sessionId: String(endpointSessionId || ''),
    tabId: Number(sender.tab?.id || 0),
    conversationKey: RelayCore.conversationKey(String(sender.tab?.url || '')),
    bindingReceiptId: String(registration?.bindingReceiptId || ''),
    attachmentGeneration: Number(pending?.attachmentGeneration || 0),
  };
  if (!relayId || pending?.kind !== 'ORCHESTRATION_RELAY_V1'
      || !registration || !orchestrationRelayBinding(expected, live)
      || Number(registration.tabId) !== live.tabId
      || String(registration.conversationKey || '') !== live.conversationKey
      || String(registration.transportInstanceId || '') !== live.instanceId
      || String(registration.sessionId || '') !== live.sessionId) {
    throw new Error('ORCHESTRATION_RELAY_BINDING_CHANGED');
  }
  return { ok: true, authorized: true, bindingAttestation: live };
}

function boundedOrchestrationResult(result) {
  const reply = String(result?.reply || '');
  if (reply.length > 1048576) throw new Error('RELAY_RESULT_TOO_LARGE');
  return { ok: result?.ok === true, reply,
    error: String(result?.error || '').slice(0, 1000),
    ambiguous: result?.ambiguous === true, failureEvidence: null };
}

async function persistOrchestrationRelayResult(message, sender) {
  await endpointSessionReady;
  const relayId = String(message?.relayId || '').trim();
  const resultPayload = boundedOrchestrationResult(message?.result || {});
  return orchestrationRelayReceiptMutation = orchestrationRelayReceiptMutation
    .catch(() => {}).then(async () => {
      const state = await loadState();
      const pending = state.pending?.[relayId] || null;
      const existing = state.resultReceipts?.[relayId] || null;
      const resultHash = await relaySha256(JSON.stringify(resultPayload));
      if (existing) {
        if (String(existing.resultHash || '') !== resultHash) throw new Error('RELAY_RESULT_CONFLICT');
        return { ok: true, duplicate: true, resultHash };
      }
      if (!pending || pending.kind !== 'ORCHESTRATION_RELAY_V1'
          || lifecycle.runtimeSenderKind(sender) !== 'CHAT_CONTENT'
          || Number(sender?.frameId || 0) !== 0 || !isChatTab(sender?.tab)
          || Number(sender?.tab?.id || 0) !== Number(pending.tabId || 0)) {
        throw new Error('ORCHESTRATION_RELAY_RESULT_PENDING_MISSING');
      }
      const expected = {
        instanceId: pending.expectedInstanceId, sessionId: pending.expectedSessionId,
        tabId: pending.tabId, conversationKey: pending.conversationKey,
        bindingReceiptId: pending.targetBindingReceipt,
        attachmentGeneration: pending.attachmentGeneration,
      };
      const registration = state.registrations?.[String(pending.to || '')] || null;
      const live = {
        instanceId: String(state.settings?.instanceId || ''),
        sessionId: String(endpointSessionId || ''),
        tabId: Number(sender.tab?.id || 0),
        conversationKey: RelayCore.conversationKey(String(sender.tab?.url || '')),
        bindingReceiptId: String(registration?.bindingReceiptId || ''),
        attachmentGeneration: Number(pending.attachmentGeneration || 0),
      };
      if (!registration || !orchestrationRelayBinding(expected, live)
          || Number(registration.tabId || 0) !== live.tabId
          || String(registration.conversationKey || '') !== live.conversationKey
          || String(registration.transportInstanceId || '') !== live.instanceId
          || String(registration.sessionId || '') !== live.sessionId
          || !orchestrationRelayBinding(live, message?.bindingAttestation)) {
        throw new Error('ORCHESTRATION_RELAY_RESULT_BINDING_MISMATCH');
      }
      const completedAt = Date.now();
      const receipt = {
        version: 1, routeId: relayId, messageHash: String(pending.messageHash || ''),
        dispatchFingerprint: String(pending.fingerprint || ''),
        from: String(pending.fromNode || pending.source || ''), to: String(pending.to || ''),
        targetBindingReceipt: String(pending.targetBindingReceipt || ''),
        instanceId: String(pending.expectedInstanceId || ''),
        sessionId: String(pending.expectedSessionId || ''),
        attachmentGeneration: Number(pending.attachmentGeneration || 0),
        submitState: pending.deliveryConfirmed === true ? 'SUBMITTED_CONFIRMED' : 'SUBMIT_UNKNOWN',
        resultState: 'RESULT_PERSISTED', resultHash, resultPayload,
        tabId: Number(pending.tabId || 0), conversationKey: String(pending.conversationKey || ''),
        stageTiming: message?.stageTiming || null,
        timing: { createdAt: Number(pending.createdAt || 0) || null,
          submittedAt: Number(pending.submittedAt || 0) || null, completedAt,
          totalMs: pending.createdAt ? Math.max(0, completedAt - Number(pending.createdAt)) : null },
        createdAt: Number(pending.createdAt || 0) || null, completedAt,
        ackState: 'UNACKED', receiverAckState: 'NOT_REQUESTED', returnState: 'NOT_REQUESTED',
      };
      const receipts = { ...(state.resultReceipts || {}), [relayId]: receipt };
      delete state.pending[relayId];
      await stateRepository.setLocal({ [RELAY_RESULT_RECEIPTS_KEY]: receipts, pending: state.pending });
      const verified = await stateRepository.getLocal(RELAY_RESULT_RECEIPTS_KEY);
      if (String(verified?.[RELAY_RESULT_RECEIPTS_KEY]?.[relayId]?.resultHash || '') !== resultHash) {
        throw new Error('RELAY_RESULT_PERSIST_VERIFY_FAILED');
      }
      return { ok: true, duplicate: false, resultHash };
    });
}
