function orchestrationContentBindingMatches(expected, actual) {
  if (!expected || !actual) return false;
  return String(actual.instanceId || '') === String(expected.instanceId || '')
    && String(actual.sessionId || '') === String(expected.sessionId || '')
    && Number(actual.tabId || 0) === Number(expected.tabId || 0)
    && String(actual.conversationKey || '') === String(expected.conversationKey || '')
    && String(actual.bindingReceiptId || '') === String(expected.bindingReceiptId || '')
    && Number(actual.attachmentGeneration || 0) === Number(expected.attachmentGeneration || 0);
}

async function authorizeOrchestrationContent(message, phase) {
  const response = await chrome.runtime.sendMessage({
    type: 'relay:orchestrationAuthorize', relayId: String(message?.relayId || ''),
    phase: String(phase || 'PROBE'), exactBinding: { ...(message?.exactBinding || {}) },
  });
  if (response?.ok !== true || response?.authorized !== true
      || !orchestrationContentBindingMatches(message?.exactBinding, response.bindingAttestation)) {
    throw new Error(response?.error || 'ORCHESTRATION_RELAY_BINDING_CHANGED');
  }
  return response.bindingAttestation;
}

async function deliverOrchestrationContentResult(record, result) {
  const completed = { ...record, kind: 'ORCHESTRATION_RELAY_V1', phase: 'completed',
    result, completedAt: Date.now() };
  saveRelayExecution(completed);
  const response = await chrome.runtime.sendMessage({
    type: 'relay:orchestrationResult', relayId: record.relayId,
    bindingAttestation: record.bindingAttestation, result,
    stageTiming: { commandReceivedAt: record.commandReceivedAt || null,
      submittedAt: record.submittedAt || null, completedAt: completed.completedAt },
  });
  if (response?.ok === true) clearRelayExecution(record.relayId);
  return response;
}

async function continueOrchestrationContent(record) {
  try {
    const reply = await waitForReply(
      Number(record.beforeCount || 0), String(record.beforeText || ''), 900000,
      Number(record.submittedAt || Date.now()),
    );
    await deliverOrchestrationContentResult(record, { ok: true, reply });
  } catch (error) {
    await deliverOrchestrationContentResult(record, {
      ok: false, error: String(error?.message || error || 'ORCHESTRATION_RELAY_REPLY_UNKNOWN'),
      ambiguous: true,
    }).catch(() => {});
  }
}

async function executeOrchestrationContent(message) {
  const relayId = String(message?.relayId || '').trim();
  const text = String(message?.text || '');
  const expected = message?.exactBinding && typeof message.exactBinding === 'object'
    ? message.exactBinding : null;
  if (!relayId || !text || text.length > 12000 || !expected
      || currentConversationKey() !== String(expected.conversationKey || '')) {
    return { ok: false, submitted: false, effectState: 'NOT_APPLIED',
      error: 'ORCHESTRATION_RELAY_ARGUMENT_OR_ROUTE_INVALID' };
  }
  const prior = loadRelayExecution();
  if (prior?.relayId) {
    if (prior.relayId !== relayId) {
      return { ok: false, submitted: false, effectState: 'NOT_APPLIED',
        error: 'ORCHESTRATION_TARGET_BUSY' };
    }
    if (prior.kind === 'ORCHESTRATION_RELAY_V1'
        && ['submitted', 'completed'].includes(String(prior.phase || ''))) {
      return { ok: true, submitted: true, replayed: true,
        bindingAttestation: prior.bindingAttestation || null };
    }
    return { ok: false, submitted: false, effectState: 'UNKNOWN',
      error: 'ORCHESTRATION_PRIOR_EFFECT_UNRESOLVED' };
  }
  if (isGenerating()) {
    return { ok: false, submitted: false, effectState: 'NOT_APPLIED',
      error: 'ORCHESTRATION_TARGET_GENERATING' };
  }
  const editor = await waitForEditor();
  if (editorDraftText(editor)) {
    return { ok: false, submitted: false, effectState: 'NOT_APPLIED',
      error: 'RELAY_COMPOSER_NOT_EMPTY' };
  }
  let bindingAttestation = await authorizeOrchestrationContent(message, 'PROBE');
  const record = {
    kind: 'ORCHESTRATION_RELAY_V1', relayId,
    conversationKey: String(expected.conversationKey || ''),
    submittedText: RelayCore.normalizeMessageText(text),
    beforeCount: getAssistantNodes().length, beforeText: lastAssistantText(),
    beforeTurnKeys: getConversationTurns().map(turnIdentity).filter(Boolean),
    routeTurnKey: '', phase: 'submit-intent', commandReceivedAt: Date.now(),
    submittedAt: null, bindingAttestation,
  };
  saveRelayExecution(record);
  try {
    setEditorText(editor, text);
    const submission = await submitEditor(editor, {
      expectedText: text,
      beforeSubmit: async () => {
        bindingAttestation = await authorizeOrchestrationContent(message, 'PRE_SUBMIT');
        return bindingAttestation;
      },
      beforeActivation: async (attestation) => {
        record.phase = 'submit-attempted';
        record.bindingAttestation = { ...(attestation || bindingAttestation) };
        saveRelayExecution(record);
        return record.bindingAttestation;
      },
    });
    record.bindingAttestation = { ...(submission.bindingAttestation || bindingAttestation) };
    record.submittedAt = Date.now();
    const turnKey = await waitForExactUserSubmission(record, 8000);
    record.routeTurnKey = turnKey;
    record.phase = 'submitted';
    saveRelayExecution(record);
    continueOrchestrationContent(record).catch(() => {});
    return { ok: true, submitted: true, relayId,
      conversationKey: record.conversationKey,
      bindingAttestation: record.bindingAttestation };
  } catch (error) {
    const current = loadRelayExecution();
    const phase = current?.relayId === relayId ? String(current.phase || '') : '';
    const unknown = ['submit-attempted', 'submitted', 'completed'].includes(phase);
    if (!unknown) {
      const liveEditor = getEditor();
      if (liveEditor && editorDraftText(liveEditor) === record.submittedText) {
        try { setEditorText(liveEditor, ''); } catch (_) {}
      }
      clearRelayExecution(relayId);
    }
    return { ok: false, submitted: false,
      effectState: unknown ? 'UNKNOWN' : 'NOT_APPLIED',
      error: String(error?.message || error || 'ORCHESTRATION_RELAY_SUBMIT_FAILED') };
  }
}

async function recoverOrchestrationContent() {
  const record = loadRelayExecution();
  if (record?.kind !== 'ORCHESTRATION_RELAY_V1' || !record.relayId
      || record.conversationKey !== currentConversationKey()) return;
  if (record.phase === 'completed' && record.result) {
    await deliverOrchestrationContentResult(record, record.result).catch(() => {});
    return;
  }
  if (record.phase === 'submitted') {
    await continueOrchestrationContent(record);
  }
}
