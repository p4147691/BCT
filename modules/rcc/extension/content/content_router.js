chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
if (String(sender?.id || '') !== String(chrome.runtime.id || '')) {
  sendResponse({ ok: false, error: 'RCC_CONTENT_SENDER_REJECTED' });
  return false;
}
if (message.type === 'relay:nodeLabelNotify') {
  const uuid = String(message.conversationKey || '').toLowerCase();
  const eventId = message.eventId;
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(uuid)
      || !Number.isSafeInteger(eventId) || eventId <= 0
      || uuid !== currentConversationKey()) {
    sendResponse({ ok: false, error: 'NODE_LABEL_CONTENT_IDENTITY_MISMATCH' });
    return false;
  }
  if (!globalThis.__bctNodeLabelDelivered) globalThis.__bctNodeLabelDelivered = new Set();
  if (globalThis.__bctNodeLabelDelivered.has(eventId)) {
    sendResponse({ ok: true, eventId, conversationKey: uuid, duplicate: true });
    return false;
  }
  window.dispatchEvent(new Event('bct:conversation-roster-changed'));
  globalThis.__bctNodeLabelDelivered.add(eventId);
  if (globalThis.__bctNodeLabelDelivered.size > 1024) {
    globalThis.__bctNodeLabelDelivered.delete(globalThis.__bctNodeLabelDelivered.values().next().value);
  }
  sendResponse({ ok: true, eventId, conversationKey: uuid });
  return false;
}
if (message.type === 'relay:recoverExecution') {
    const storedRecord = loadRelayExecution();
    const suppliedRecord = message.recoveryRecord && typeof message.recoveryRecord === 'object'
      ? message.recoveryRecord : null;
    const record = storedRecord?.relayId ? storedRecord : suppliedRecord;
    const relayId = String(message.relayId || '');
    if (!record?.relayId || (relayId && record.relayId !== relayId)) {
      sendResponse({ ok: false, recovered: false, error: 'RELAY_RECOVERY_RECORD_NOT_FOUND' });
      return;
    }
    const conversationKey = String(record.conversationKey || currentConversationKey());
    if (!conversationKey || conversationKey !== currentConversationKey()) {
      sendResponse({ ok: false, recovered: false, error: 'RELAY_RECOVERY_IDENTITY_MISMATCH' });
      return;
    }
    Promise.resolve().then(() => recoverCompletedReplyFromDom({ ...record, conversationKey }))
      .then((recoveredReply) => sendResponse({ ok: true, recovered: true, relayId: record.relayId, recoveredReply }))
      .catch((error) => sendResponse({ ok: false, recovered: false, error: error.message }));
    return true;
  }

// Read-only original-effect proof. Never synthesizes an execution record,
// submits a prompt, or promotes an UNKNOWN delivery.
if (message.type === 'relay:deliveryRecoveryProof') {
  Promise.resolve().then(async () => {
    const id = String(message.deliveryId || '');
    const key = String(message.conversationKey || '').toLowerCase();
    const expectedHash = String(message.requestSha256 || '');
    const record = loadRelayExecution();
    if (!id || !record || record.relayId !== id
        || record.conversationKey !== key || currentConversationKey() !== key
        || !['submit-activated', 'submitted', 'completed'].includes(String(record.phase || ''))
        || !Array.isArray(record.beforeTurnKeys)
        || !/^[a-f0-9]{64}$/.test(expectedHash)) {
      return { ok: false, error: 'DELIVERY_RECOVERY_ORIGINAL_RECORD_UNPROVEN' };
    }
    const actualHash = await newChatTextSha256(record.submittedText);
    if (actualHash !== expectedHash) {
      return { ok: false, error: 'DELIVERY_RECOVERY_REQUEST_HASH_MISMATCH' };
    }
    const routed = resolveRoutedTurn(record);
    if (!routed.ok || !routed.turnKey || !submittedPromptMatchesTurn(record, routed.turn)) {
      return { ok: false, error: 'DELIVERY_RECOVERY_EXACT_USER_TURN_UNPROVEN' };
    }
    if (isGenerating() || turnGenerationInterrupted(routed.turn)) {
      return { ok: false, error: 'DELIVERY_RECOVERY_REPLY_NOT_TERMINAL' };
    }
    const reply = recoverCompletedReplyFromDom(record);
    if (typeof reply !== 'string' || !reply || reply.length > 12000) {
      return { ok: false, error: 'DELIVERY_RECOVERY_REPLY_INVALID' };
    }
    return {
      ok: true, deliveryId: id, conversationKey: key, requestSha256: actualHash,
      turnKey: routed.turnKey, phase: record.phase, responseText: reply,
      responseSha256: await newChatTextSha256(reply), responseLength: reply.length
    };
  }).then(sendResponse).catch((error) => sendResponse({
    ok: false, error: String(error?.message || error || 'DELIVERY_RECOVERY_FAILED').slice(0, 128)
  }));
  return true;
}
// Exact read-only proof for a Manager return whose activation ACK was lost.
// The full framed return contains a Delivery id and result hash, so require one
// and only one normalized user turn.  This never clicks or edits the composer.
if (message.type === 'relay:exactUserTurnProof') {
  Promise.resolve().then(async () => {
    const id = String(message.deliveryId || '');
    const key = String(message.conversationKey || '').trim().toLowerCase();
    const text = RelayCore.normalizeMessageText(String(message.text || ''));
    const expectedHash = String(message.submittedSha256 || '').trim().toLowerCase();
    if (!id || !key || currentConversationKey() !== key || text.length > 12000
        || !/^[a-f0-9]{64}$/.test(expectedHash)
        || (text && await newChatTextSha256(text) !== expectedHash)) {
      return { ok: false, error: 'RELAY_EXACT_USER_TURN_ARGUMENT_INVALID' };
    }
    const matches = text
      ? getConversationTurns().filter((turn) =>
        submittedPromptMatchesTurn({ submittedText: text, conversationKey: key }, turn))
      : await exactUserTurnsBySubmittedSha256(expectedHash);
    if (matches.length !== 1) {
      return { ok: false, error: matches.length > 1
        ? 'RELAY_EXACT_USER_TURN_AMBIGUOUS' : 'RELAY_EXACT_USER_TURN_NOT_FOUND' };
    }
    const turn = matches[0];
    const beforeAssistantCount = getAssistantNodes().filter((node) => {
      if (!node || turn.contains?.(node)) return false;
      return !!(node.compareDocumentPosition?.(turn) & Node.DOCUMENT_POSITION_FOLLOWING);
    }).length;
    return { ok: true, deliveryId: id, conversationKey: key,
      submittedSha256: expectedHash, turnKey: turnIdentity(turn),
      beforeAssistantCount };
  }).then(sendResponse).catch((error) => sendResponse({
    ok: false, error: String(error?.message || error || 'RELAY_EXACT_USER_TURN_PROOF_FAILED').slice(0, 128)
  }));
  return true;
}
// Recover one already completed Manager reply after its page-session route was
// deliberately retired. Identity comes from the exact submitted user-turn
// hash plus the previously captured reply hash/length. This is read-only.
if (message.type === 'relay:exactReplyProof') {
  Promise.resolve().then(async () => {
    const id = String(message.deliveryId || '');
    const key = String(message.conversationKey || '').trim().toLowerCase();
    const submittedSha256 = String(message.submittedSha256 || '').trim().toLowerCase();
    const workerConversationKey = String(
      message.workerConversationKey || '').trim().toLowerCase();
    const workerResultSha256 = String(
      message.workerResultSha256 || '').trim().toLowerCase();
    const expectedResponseSha256 = String(
      message.expectedResponseSha256 || '').trim().toLowerCase();
    const expectedResponseLength = Number(message.expectedResponseLength);
    if (!id || !key || currentConversationKey() !== key
        || !/^[a-f0-9]{64}$/.test(submittedSha256)
        || !/^[a-f0-9]{64}$/.test(expectedResponseSha256)
        || !Number.isInteger(expectedResponseLength)
        || expectedResponseLength <= 0 || expectedResponseLength > 12000) {
      return { ok: false, error: 'RELAY_EXACT_REPLY_ARGUMENT_INVALID' };
    }
    let matches = await exactUserTurnsBySubmittedSha256(submittedSha256);
    let identityProof = 'submitted_sha256';
    // ChatGPT renders Markdown in an old user turn, so the visible DOM can
    // legitimately omit backticks that were present in the exact submitted
    // text.  RC30 terminal receipts no longer retain that text.  In that
    // legacy shape, use the immutable return-frame identity which was part of
    // the submitted user turn: Delivery id, both conversation ids, and the
    // captured Worker result hash.  Require exactly one matching turn; this is
    // read-only and does not weaken duplicate-turn detection.
    if (matches.length === 0
        && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(
          workerConversationKey)
        && /^[a-f0-9]{64}$/.test(workerResultSha256)) {
      matches = getConversationTurns().filter((candidate) => {
        const rendered = turnUserText(candidate);
        const open = '[BCT_MANAGER_RETURN_CONTEXT_V1]';
        const close = '[/BCT_MANAGER_RETURN_CONTEXT_V1]';
        const start = rendered.indexOf(open);
        const end = rendered.indexOf(close, start + open.length);
        if (start < 0 || end <= start) return false;
        let context;
        try {
          context = JSON.parse(rendered.slice(start + open.length, end).trim());
        } catch (_) {
          return false;
        }
        return context?.delivery_id === id
          && String(context?.manager_conversation_uuid || '').toLowerCase() === key
          && String(context?.worker_conversation_uuid || '').toLowerCase()
            === workerConversationKey
          && String(context?.worker_result_sha256 || '').toLowerCase()
            === workerResultSha256;
      });
      identityProof = 'manager_return_frame';
    }
    if (matches.length !== 1) {
      return { ok: false, error: matches.length > 1
        ? 'RELAY_EXACT_REPLY_USER_TURN_AMBIGUOUS' : 'RELAY_EXACT_REPLY_USER_TURN_NOT_FOUND' };
    }
    const turn = matches[0];
    if (turnGenerationInterrupted(turn)) {
      return { ok: false, error: 'RELAY_EXACT_REPLY_INTERRUPTED' };
    }
    const completeState = turnCompletionState(turn) === 'complete';
    const completionUiReady = !!turn.querySelector(
      'button[data-testid="copy-turn-action-button"],button[data-testid*="copy"],button[aria-label="Copy"],button[aria-label="복사"],button[aria-label="복사하기"]'
    );
    if (!(completeState && completionUiReady) && turnIsGenerating(turn)) {
      return { ok: false, error: 'RELAY_EXACT_REPLY_STILL_GENERATING' };
    }
    const selected = RelayCore.selectAssistantCandidate(assistantCandidatesForTurn(turn));
    if (!selected.ok || typeof selected.candidate?.text !== 'string'
        || !selected.candidate.text || selected.candidate.text.length > 12000) {
      return { ok: false, error: 'RELAY_EXACT_REPLY_DOM_UNKNOWN' };
    }
    if (!completeState && !completionUiReady) {
      return { ok: false, error: 'RELAY_EXACT_REPLY_FINAL_STATE_UNKNOWN' };
    }
    const responseText = selected.candidate.text;
    const responseSha256 = await newChatTextSha256(responseText);
    if (responseSha256 !== expectedResponseSha256
        || responseText.length !== expectedResponseLength) {
      return { ok: false, error: 'RELAY_EXACT_REPLY_IDENTITY_MISMATCH',
        responseSha256, responseLength: responseText.length };
    }
    return { ok: true, deliveryId: id, conversationKey: key,
      submittedSha256, responseText, responseSha256,
      responseLength: responseText.length, turnKey: turnIdentity(turn),
      identityProof };
  }).then(sendResponse).catch((error) => sendResponse({
    ok: false, error: String(error?.message || error
      || 'RELAY_EXACT_REPLY_PROOF_FAILED').slice(0, 128)
  }));
  return true;
}
if (message.type === 'relay:activityProbe') {
    sampleJsHeapTelemetry();


    sendResponse({


      ok: true,


      generating: isGenerating(),

      composerEmpty: !editorDraftText(getEditor()),

      activeRelayId: String(loadRelayExecution()?.relayId || ''),

      reasoning: currentReasoningObservation(),

      connection: connectionProblem(),


      telemetry: typeof telemetry === 'object' ? {generationState:telemetry.generationState||'',readiness:telemetry.readiness||'IDLE',lastActivityAt:telemetry.lastActivityAt||null,lastCommandAt:telemetry.lastCommandAt||null,generationStartedAt:telemetry.generationStartedAt||null,generationFinishedAt:telemetry.generationFinishedAt||null,queueDelayMs:telemetry.queueDelayMs??null,generationTimeMs:telemetry.generationTimeMs??null,totalResponseTimeMs:telemetry.totalResponseTimeMs??null,rollingAvgResponseMs:telemetry.rollingAvgResponseMs??null,rollingP95ResponseMs:telemetry.rollingP95ResponseMs??null,performanceState:telemetry.performanceState||'NORMAL',user_count:telemetry.user_count??null,assistant_count:telemetry.assistant_count??null,turns:telemetry.turns??null,rendered_chars:telemetry.rendered_chars??null,js_heap_used_mb:telemetry.js_heap_used_mb??null,js_heap_limit_mb:telemetry.js_heap_limit_mb??null,usage_estimate_kind:telemetry.usage_estimate_kind||'incremental-message-chars-v1',buildVersion:RCC_BUILD_VERSION} : null


    });


    return;


  }

if (message.type === 'relay:deliveryReadiness') {
    const expectedConversationKey = String(message.conversationKey || '').trim().toLowerCase();
    const actualConversationKey = currentConversationKey();
    const editor = getEditor();
    const active = loadRelayExecution();
    sendResponse({
      ok: !!expectedConversationKey && actualConversationKey === expectedConversationKey,
      conversationKey: actualConversationKey,
      generating: isGenerating(),
      composerEmpty: !!editor && !editorDraftText(editor),
      activeRelayId: String(active?.relayId || ''),
      activeRelayPhase: String(active?.phase || ''),
      sendReady: isSendReady(),
    });
    return;
  }

// Retire only one exact orphaned BCT draft.  This never clicks a submit
// control and refuses user-authored or currently active relay content.  The
// caller must already know the SHA-256 recorded for the superseded Delivery.
if (message.type === 'relay:retireComposerDraft') {
  Promise.resolve().then(async () => {
    const expectedConversationKey = String(message.conversationKey || '').trim().toLowerCase();
    const expectedDraftSha256 = String(message.expectedDraftSha256 || '').trim().toLowerCase();
    const supersededDeliveryId = String(message.supersededDeliveryId || '').trim();
    const actualConversationKey = currentConversationKey();
    if (!expectedConversationKey || actualConversationKey !== expectedConversationKey
        || !/^[a-f0-9]{64}$/.test(expectedDraftSha256)
        || !/^[A-Za-z0-9_.:-]{1,80}$/.test(supersededDeliveryId)) {
      return { ok: false, retired: false, effectState: 'NOT_APPLIED',
        error: 'RELAY_DRAFT_RETIRE_IDENTITY_INVALID' };
    }
    if (isGenerating()) {
      return { ok: false, retired: false, effectState: 'NOT_APPLIED',
        error: 'RELAY_DRAFT_RETIRE_TARGET_GENERATING' };
    }
    const active = loadRelayExecution();
    if (active?.relayId) {
      if (String(active.relayId || '') !== supersededDeliveryId
          || String(active.conversationKey || '').trim().toLowerCase() !== expectedConversationKey
          || String(active.phase || '') !== 'submit-activated') {
        return { ok: false, retired: false, effectState: 'NOT_APPLIED',
          error: 'RELAY_DRAFT_RETIRE_ACTIVE_IDENTITY_MISMATCH' };
      }
      const activeTextSha256 = await newChatTextSha256(active.submittedText || '');
      if (activeTextSha256 !== expectedDraftSha256) {
        return { ok: false, retired: false, effectState: 'NOT_APPLIED',
          error: 'RELAY_DRAFT_RETIRE_ACTIVE_HASH_MISMATCH', activeTextSha256 };
      }
      const routed = resolveRoutedTurn(active);
      if (routed?.ok === true || routed?.reason !== 'ROUTE_TURN_NOT_RESOLVED') {
        return { ok: false, retired: false, effectState: 'NOT_APPLIED',
          error: 'RELAY_DRAFT_RETIRE_ACTIVE_ROUTE_NOT_ABSENT',
          routedReason: String(routed?.reason || 'ROUTE_TURN_PRESENT') };
      }
    }
    const editor = getEditor();
    const draft = editor ? editorDraftText(editor) : '';
    if (!editor || !draft) {
      return { ok: false, retired: false, effectState: 'NOT_APPLIED',
        error: 'RELAY_DRAFT_RETIRE_COMPOSER_EMPTY' };
    }
    const actualDraftSha256 = await newChatTextSha256(draft);
    if (actualDraftSha256 !== expectedDraftSha256) {
      return { ok: false, retired: false, effectState: 'NOT_APPLIED',
        error: 'RELAY_DRAFT_RETIRE_HASH_MISMATCH', actualDraftSha256 };
    }
    setEditorText(editor, '');
    await new Promise((resolve) => setTimeout(resolve, 0));
    const liveEditor = getEditor();
    if (!liveEditor || editorDraftText(liveEditor)) {
      throw new Error('RELAY_DRAFT_RETIRE_CLEAR_UNPROVEN');
    }
    let retiredExecutionId = '';
    if (active?.relayId) {
      retiredExecutionId = supersededDeliveryId;
      retiredRelayExecutions.add(retiredExecutionId);
      clearRelayExecution(retiredExecutionId);
      if (loadRelayExecution()?.relayId) {
        throw new Error('RELAY_DRAFT_RETIRE_EXECUTION_CLEAR_UNPROVEN');
      }
    }
    return {
      ok: true, retired: true, effectState: 'APPLIED',
      conversationKey: actualConversationKey,
      draftSha256: actualDraftSha256,
      draftLength: draft.length,
      retiredExecutionId,
      composerEmpty: true,
    };
  }).then(sendResponse).catch((error) => sendResponse({
    ok: false, retired: false, effectState: 'UNKNOWN',
    error: String(error?.message || error || 'RELAY_DRAFT_RETIRE_UNKNOWN').slice(0, 128),
  }));
  return true;
}

// Read exactly the latest rendered Assistant turn in this exact conversation.
// It is intentionally an observation: it does not bind the answer to a
// previous send operation and never changes the page or composer.
if (message.type === 'relay:readLatestAssistant') {
  Promise.resolve().then(async () => {
    const expectedConversationKey = String(message.conversationKey || '').trim().toLowerCase();
    const actualConversationKey = currentConversationKey();
    if (!expectedConversationKey || actualConversationKey !== expectedConversationKey) {
      return { ok: false, error: 'READ_LATEST_ASSISTANT_CONVERSATION_MISMATCH' };
    }
    const node = lastAssistantNode();
    const responseText = node ? messageUnitText(node, 'assistant') : '';
    if (responseText.length > 12000) {
      return { ok: false, error: 'READ_LATEST_ASSISTANT_TOO_LARGE' };
    }
    const generating = isGenerating();
    const terminal = !generating && (!!node && hasCompletionAction());
    const assistantUnits = getAssistantNodes();
    const userUnits = getMessageUnits('user');
    const latestUserUnit = userUnits.length ? userUnits[userUnits.length - 1] : null;
    const sourceUserUnit = node ? userUnits.filter((unit) =>
      !!(unit.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING)
    ).at(-1) : null;
    const latestUserTurnKey = latestUserUnit ? turnIdentity(
      latestUserUnit.closest('[data-turn-key], [data-content-search-turn-key], [data-testid^="conversation-turn-"]')
      || latestUserUnit
    ) : '';
    const responseSourceUserTurnKey = sourceUserUnit ? turnIdentity(
      sourceUserUnit.closest('[data-turn-key], [data-content-search-turn-key], [data-testid^="conversation-turn-"]')
      || sourceUserUnit
    ) : '';
    const latestUserSha256 = latestUserUnit
      ? await newChatTextSha256(messageUnitText(latestUserUnit, 'user')) : '';
    const responseSourceUserSha256 = sourceUserUnit
      ? await newChatTextSha256(messageUnitText(sourceUserUnit, 'user')) : '';
    const turn = node?.closest('[data-turn-key], [data-content-search-turn-key], [data-testid^="conversation-turn-"]');
    const responseTurnKey = turn?.getAttribute('data-turn-key')
      || turn?.getAttribute('data-content-search-turn-key')
      || turn?.getAttribute('data-testid') || '';
    const composer = document.querySelector(
      '#prompt-textarea, div[contenteditable="true"][data-virtualkeyboard="true"], '
      + 'textarea[name="prompt-textarea"], form div[contenteditable="true"][role="textbox"]'
    );
    const inputReady = !!(terminal && composer
      && !composer.disabled && composer.getAttribute('aria-disabled') !== 'true'
      && !composer.closest('[inert]'));
    return {
      ok: true, conversationKey: actualConversationKey,
      observationState: node ? (terminal ? 'TERMINAL' : 'IN_PROGRESS') : 'EMPTY',
      generating, terminal, inputReady, responseTurnKey,
      latestUserTurnKey, latestUserSha256,
      responseSourceUserTurnKey, responseSourceUserSha256,
      responseTurnCount: assistantUnits.length,
      responseText,
      responseSha256: responseText ? await newChatTextSha256(responseText) : '',
      responseLength: responseText.length,
      observedAt: Date.now(),
    };
  }).then(sendResponse).catch((error) => sendResponse({
    ok: false, error: String(error?.message || error || 'READ_LATEST_ASSISTANT_FAILED').slice(0, 128),
  }));
  return true;
}

if (message.type === 'relay:retireExecution') {
  Promise.resolve().then(async () => {
    const relayId = String(message.relayId || '').trim();
    const expectedConversationKey = String(message.conversationKey || '').trim().toLowerCase();
    const expectedRequestSha256 = String(message.expectedRequestSha256 || '').trim().toLowerCase();
    const expectedResponseSha256 = String(message.expectedResponseSha256 || '').trim().toLowerCase();
    const expectedResponseLength = Number(message.expectedResponseLength);
    const active = loadRelayExecution();
    if (!relayId || active?.relayId !== relayId
        || (expectedConversationKey && (currentConversationKey() !== expectedConversationKey
          || String(active.conversationKey || '').trim().toLowerCase() !== expectedConversationKey))) {
      return { ok: false, retired: false, effectState: 'NOT_APPLIED',
        error: 'RELAY_RETIRE_ID_MISMATCH' };
    }
    const requestSha256 = await newChatTextSha256(String(active.submittedText || ''));
    if (!/^[a-f0-9]{64}$/.test(expectedRequestSha256)
        || requestSha256 !== expectedRequestSha256) {
      return { ok: false, retired: false, effectState: 'NOT_APPLIED',
        error: 'RELAY_RETIRE_REQUEST_IDENTITY_MISMATCH', requestSha256 };
    }
    let responseText;
    try {
      responseText = recoverCompletedReplyFromDom(active);
    } catch (error) {
      return { ok: false, retired: false, effectState: 'NOT_APPLIED',
        error: String(error?.message || error || 'RELAY_RETIRE_REPLY_NOT_CAPTURED').slice(0, 128) };
    }
    if (!responseText) {
      return { ok: false, retired: false, effectState: 'NOT_APPLIED',
        error: 'RELAY_RETIRE_REPLY_NOT_CAPTURED' };
    }
    const responseSha256 = await newChatTextSha256(responseText);
    if ((expectedResponseSha256 && (!/^[a-f0-9]{64}$/.test(expectedResponseSha256)
          || responseSha256 !== expectedResponseSha256))
        || (Number.isInteger(expectedResponseLength) && expectedResponseLength >= 0
          && responseText.length !== expectedResponseLength)) {
      return { ok: false, retired: false, effectState: 'NOT_APPLIED',
        error: 'RELAY_RETIRE_RESPONSE_IDENTITY_MISMATCH', responseSha256,
        responseLength: responseText.length };
    }
    retiredRelayExecutions.add(relayId);
    clearRelayExecution(relayId);
    if (loadRelayExecution()?.relayId) throw new Error('RELAY_RETIRE_CLEAR_UNPROVEN');
    if (typeof scheduleRelayGenerationStateCheck === 'function') {
      scheduleRelayGenerationStateCheck(true);
    }
    return { ok: true, retired: true, effectState: 'APPLIED', relayId,
      conversationKey: expectedConversationKey || currentConversationKey(),
      requestSha256, responseSha256, responseLength: responseText.length, executionAbsent: true };
  }).then(sendResponse).catch((error) => sendResponse({
    ok: false, retired: false, effectState: 'UNKNOWN',
    error: String(error?.message || error || 'RELAY_RETIRE_FAILED').slice(0, 128),
  }));
  return true;
  }

if (message.type === 'relay:probe') {
    sampleJsHeapTelemetry();


    const nodes = getAssistantNodes();


    const activeExecution = loadRelayExecution();


    const deferredQueue = loadDeferredRelayQueue();


    sendResponse({


      ok: true,


      contentVersion: 'markerless-v3-stable-final',

      buildVersion: RCC_BUILD_VERSION,


      generating: isGenerating(),

      connection: connectionProblem(),

      activeExecution: activeExecution?.relayId ? {

        relayId: String(activeExecution.relayId), phase: String(activeExecution.phase || ''),

        conversationKey: String(activeExecution.conversationKey || ''),

        submittedAt: Number(activeExecution.submittedAt || 0) || null

      } : null,

      deferredQueueDepth: deferredQueue.length,


      telemetry: typeof telemetry === 'object' ? {generationState:telemetry.generationState||'',readiness:telemetry.readiness||'IDLE',lastActivityAt:telemetry.lastActivityAt||null,lastCommandAt:telemetry.lastCommandAt||null,generationStartedAt:telemetry.generationStartedAt||null,generationFinishedAt:telemetry.generationFinishedAt||null,queueDelayMs:telemetry.queueDelayMs??null,generationTimeMs:telemetry.generationTimeMs??null,totalResponseTimeMs:telemetry.totalResponseTimeMs??null,rollingAvgResponseMs:telemetry.rollingAvgResponseMs??null,rollingP95ResponseMs:telemetry.rollingP95ResponseMs??null,performanceState:telemetry.performanceState||'NORMAL',user_count:telemetry.user_count??null,assistant_count:telemetry.assistant_count??null,turns:telemetry.turns??null,rendered_chars:telemetry.rendered_chars??null,js_heap_used_mb:telemetry.js_heap_used_mb??null,js_heap_limit_mb:telemetry.js_heap_limit_mb??null,usage_estimate_kind:telemetry.usage_estimate_kind||'incremental-message-chars-v1'} : null,


      assistantCount: nodes.length,


      completionUiReady: hasCompletionAction(),


      sendReady: isSendReady(),


      assistantStatus: lastAssistantNode()?.getAttribute('data-message-status') || '',


      assistantClass: String(lastAssistantNode()?.className || ''),


      assistantButtons: Array.from(lastAssistantNode()?.querySelectorAll('button') || []).slice(0, 20).map((b) => ({


        testid: b.getAttribute('data-testid') || '', aria: b.getAttribute('aria-label') || '', disabled: !!b.disabled


      })),


      composerButtons: Array.from(document.querySelectorAll('form button')).slice(-20).map((b) => ({


        testid: b.getAttribute('data-testid') || '', aria: b.getAttribute('aria-label') || '', disabled: !!b.disabled,


        type: b.getAttribute('type') || ''


      }))


    });


    return;


  }

if (message.type === 'relay:simpleExecute') {

    executeSimpleRelayV0(message).then(sendResponse).catch((error) => sendResponse({
      ok: false, submitted: false, effectState: 'UNKNOWN', error: error.message
    }));

    return true;


  }

if (message.type === 'relay:orchestrationExecute') {
    executeOrchestrationContent(message).then(sendResponse).catch((error) => sendResponse({
      ok: false, submitted: false, effectState: 'UNKNOWN', error: error.message
    }));
    return true;
  }

if (message.type === 'relay:simpleReadReply') {

    readSimpleRelayV0Reply(message).then(sendResponse).catch((error) => sendResponse({
      ok: false, effectState: 'NOT_APPLIED', error: error.message
    }));

    return true;


  }

if (message.type === 'relay:newChatExecute') {

    executeNewChatBootstrap(message).then(sendResponse).catch((error) => sendResponse({
      ok: false, submitted: false, effectState: 'UNKNOWN', error: error.message
    }));

    return true;


  }

if (message.type === 'relay:newChatStatus') {

    readNewChatBootstrapStatus(message).then(sendResponse).catch((error) => sendResponse({
      ok: false, effectState: 'NOT_APPLIED', error: error.message
    }));

    return true;


  }

if (message.type === 'relay:renameConversation') {

    renameConversationUi(message).then(sendResponse).catch((error) => sendResponse({
      ok: false,
      effectState: String(error?.effectState || 'UNKNOWN'),
      error: String(error?.message || error || 'RENAME_UI_UNKNOWN'),
      renameDiagnostic: error?.renameDiagnostic || null
    }));

    return true;


  }
  sendResponse({ ok: false, error: `RCC_CONTENT_MESSAGE_DISABLED:${String(message?.type || '')}` });
  return false;
});


const telemetryKey = 'dwActTelemetryV1';
