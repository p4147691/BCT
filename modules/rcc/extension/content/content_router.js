chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
if (String(sender?.id || '') !== String(chrome.runtime.id || '')) {
  sendResponse({ ok: false, error: 'RCC_CONTENT_SENDER_REJECTED' });
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
if (message.type === 'relay:activityProbe') {
    sampleJsHeapTelemetry();


    sendResponse({


      ok: true,


      generating: isGenerating(),

      connection: connectionProblem(),


      telemetry: typeof telemetry === 'object' ? {generationState:telemetry.generationState||'',readiness:telemetry.readiness||'IDLE',lastActivityAt:telemetry.lastActivityAt||null,lastCommandAt:telemetry.lastCommandAt||null,generationStartedAt:telemetry.generationStartedAt||null,generationFinishedAt:telemetry.generationFinishedAt||null,queueDelayMs:telemetry.queueDelayMs??null,generationTimeMs:telemetry.generationTimeMs??null,totalResponseTimeMs:telemetry.totalResponseTimeMs??null,rollingAvgResponseMs:telemetry.rollingAvgResponseMs??null,rollingP95ResponseMs:telemetry.rollingP95ResponseMs??null,performanceState:telemetry.performanceState||'NORMAL',user_count:telemetry.user_count??null,assistant_count:telemetry.assistant_count??null,turns:telemetry.turns??null,rendered_chars:telemetry.rendered_chars??null,js_heap_used_mb:telemetry.js_heap_used_mb??null,js_heap_limit_mb:telemetry.js_heap_limit_mb??null,usage_estimate_kind:telemetry.usage_estimate_kind||'incremental-message-chars-v1',buildVersion:RCC_BUILD_VERSION} : null


    });


    return;


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
      error: String(error?.message || error || 'RENAME_UI_UNKNOWN')
    }));

    return true;


  }
  sendResponse({ ok: false, error: `RCC_CONTENT_MESSAGE_DISABLED:${String(message?.type || '')}` });
  return false;
});


const telemetryKey = 'dwActTelemetryV1';
