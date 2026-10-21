function handleRuntimeMessage(message, sender, sendResponse) {
  (async () => {
    const messageDecision = RccLegacyCommandPolicy.runtimeMessage(message?.type);
    if (!messageDecision.allowed) throw new Error(RccLegacyCommandPolicy.rejectCode('RUNTIME_MESSAGE', message?.type, messageDecision));
    const senderKind = lifecycle.runtimeSenderKind(sender);
    const expectedSenderKind = message?.type === 'relay:getState'
      ? 'EXTENSION_PAGE' : 'CHAT_CONTENT';
    if (senderKind !== expectedSenderKind) {
      throw new Error(`RCC_RUNTIME_SENDER_REJECTED:${String(message?.type || '')}`);
    }
    if (message.type === 'relay:getPendingStatus') {


          const state = await loadState();


          const relayId = String(message.relayId || '');


          const pending = state.pending?.[relayId];


          const tabId = Number(sender.tab?.id);


          const key = RelayCore.conversationKey(sender.tab?.url || '');


          if (!pending) {

            const receipt = state.resultReceipts?.[relayId] || null;

            const exactDurableResult = receipt?.resultState === 'RESULT_PERSISTED'

              && Number(receipt.tabId) === tabId

              && !!String(receipt.conversationKey || '')

              && String(receipt.conversationKey) === key;

            if (exactDurableResult) return { ok: true, found: false, completed: true,

              relayId, resultHash: String(receipt.resultHash || '') };

            return { ok: false, found: false };

          }


          if (Number(pending.tabId) !== tabId) return { ok: false, found: false };


          if (pending.conversationKey && key !== pending.conversationKey) return { ok: false, found: false, error: 'PENDING_IDENTITY_MISMATCH' };


          return { ok: true, found: true, relayId,


            deliveryConfirmed: pending.deliveryConfirmed === true,


            networkStartedAt: Number(pending.networkStartedAt || 0) || null,


            networkCompletedAt: Number(pending.networkCompletedAt || 0) || null,


            networkOk: pending.networkOk !== false,


            networkError: String(pending.networkError || '') };


        }

    if (message.type === 'relay:getState') {


          const state = await loadState();


          const tabs = (await getChatTabs()).map(publicTab);


          return { ok: true, tabs, registrations: state.registrations, settings: state.settings,
            results: state.results, simpleRelayV0Binding: state.simpleRelayV0Binding };


        }

    if (message.type === 'relay:activity') {


          const tab = sender.tab;


          if (!isChatTab(tab) || tab?.id == null) return { ok: false, error: 'Activity source is not an open ChatGPT tab' };


          const previous = endpointPresence.get(tab.id);


          const endpoint = endpointFromTab(tab, 'OPEN', 'activity');


          await attachEndpointWindowBounds(endpoint);


          endpoint.generating = !!message.generating;

          endpoint.connection = message.connection && typeof message.connection === 'object'

            ? message.connection

            : (previous?.connection && typeof previous.connection === 'object' ? previous.connection : null);


          const incomingTelemetry = message.telemetry && typeof message.telemetry === 'object' ? message.telemetry : null;


          const previousTelemetry = previous?.telemetry && typeof previous.telemetry === 'object' ? previous.telemetry : null;


          endpoint.telemetry = { ...(previousTelemetry || {}), ...(incomingTelemetry || {}) };


          endpoint.telemetry.generationState = endpoint.generating ? 'GENERATING' : 'IDLE';


          const incomingReadiness = String(incomingTelemetry?.readiness || '');


          const previousReadiness = String(previousTelemetry?.readiness || '');


          if (incomingReadiness) endpoint.telemetry.readiness = incomingReadiness;


          else if (endpoint.generating) endpoint.telemetry.readiness = 'BUSY';


          else if (previousReadiness === 'BUSY') endpoint.telemetry.readiness = 'IDLE';


          else endpoint.telemetry.readiness = previousReadiness || 'IDLE';


          if (previous && previous.generating === endpoint.generating && endpointComparable(previous) === endpointComparable(endpoint) && JSON.stringify(previous?.telemetry || null) === JSON.stringify(endpoint.telemetry || null)) return { ok: true, unchanged: true };


          endpointPresence.set(tab.id, endpoint);


          await publishEndpointDelta(endpoint, 'activity');


          return { ok: true, generating: endpoint.generating };


        }
    if (message.type === 'relay:orchestrationAuthorize') {
          return authorizeOrchestrationRelay(message, sender);
        }
    if (message.type === 'relay:orchestrationResult') {
          return persistOrchestrationRelayResult(message, sender);
        }
    throw new Error(`Unknown message type: ${message.type}`);
  })().then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));
  return true;
}
