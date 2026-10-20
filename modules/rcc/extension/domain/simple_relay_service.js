async function sendToChatTab(tabId, message) {
  return browserGateway.sendWithReceiver(tabId, message);

}

function simpleRelayV0TabsForBinding(tabs, binding) {
  const manager = tabs.filter((tab) => RelayCore.conversationKey(tab.url || '') === binding.managerConversationKey);
  const worker = tabs.filter((tab) => RelayCore.conversationKey(tab.url || '') === binding.workerConversationKey);
  if (manager.length !== 1 || worker.length !== 1) {
    throw new Error('SIMPLE_RELAY_ENDPOINT_NOT_UNIQUE_OR_OPEN');
  }
  return { manager: manager[0], worker: worker[0] };
}

async function bindSimpleRelayV0(message) {
  const binding = SimpleRelayV0.binding(message.managerConversationKey, message.workerConversationKey);
  const tabs = simpleRelayV0TabsForBinding(await getChatTabs(), binding);
  await stateRepository.setLocal({ [SIMPLE_RELAY_V0_BINDING_KEY]: binding });
  return {
    ok: true, binding,
    manager: { tabId: tabs.manager.id, windowId: tabs.manager.windowId },
    worker: { tabId: tabs.worker.id, windowId: tabs.worker.windowId },
  };
}

async function sendSimpleRelayV0(message, requestId) {
  const state = await loadState();
  const request = SimpleRelayV0.request({
    binding: state.simpleRelayV0Binding,
    from: message.from,
    operationId: message.operationId || requestId,
    text: message.text,
  });
  const fingerprint = await relaySha256(JSON.stringify([
    request.from, request.to, request.sourceConversationKey,
    request.targetConversationKey, request.text,
  ]));
  const receipts = await readSimpleRelayV0Receipts();
  const existing = receipts[request.operationId];
  if (existing) {
    if (existing.fingerprint !== fingerprint) throw new Error('SIMPLE_RELAY_OPERATION_ID_REUSE_MISMATCH');
    if (existing.state === 'SUBMITTED') return { ok: true, replayed: true, receipt: existing };
    throw new Error('SIMPLE_RELAY_PRIOR_EFFECT_UNRESOLVED');
  }
  const tabs = simpleRelayV0TabsForBinding(await getChatTabs(), state.simpleRelayV0Binding);
  const targetTab = request.to === SimpleRelayV0.ROLE.MANAGER ? tabs.manager : tabs.worker;
  const intent = {
    version: 0, operationId: request.operationId, fingerprint,
    from: request.from, to: request.to, targetConversationKey: request.targetConversationKey,
    textSha256: await relaySha256(request.text), textLength: request.text.length,
    state: 'INTENT', updatedAt: Date.now(),
  };
  await writeSimpleRelayV0Receipt(request.operationId, intent);
  let ack;
  try {
    ack = await sendToChatTab(targetTab.id, {
      type: 'relay:simpleExecute', relayId: request.operationId,
      conversationKey: request.targetConversationKey, text: request.text,
    });
  } catch (error) {
    const receipt = { ...intent, state: 'UNKNOWN', updatedAt: Date.now(),
      error: String(error?.message || error || 'SIMPLE_RELAY_TRANSPORT_UNKNOWN').slice(0, 200) };
    await writeSimpleRelayV0Receipt(request.operationId, receipt);
    return { ok: false, ambiguous: true, receipt };
  }
  if (ack?.ok === true && ack.submitted === true && ack.conversationKey === request.targetConversationKey) {
    const receipt = { ...intent, state: 'SUBMITTED', tabId: targetTab.id,
      windowId: targetTab.windowId, beforeAssistantCount: Number(ack.beforeAssistantCount || 0),
      updatedAt: Date.now() };
    await writeSimpleRelayV0Receipt(request.operationId, receipt);
    return { ok: true, receipt };
  }
  const notApplied = ack?.effectState === 'NOT_APPLIED' || ack?.submitted === false;
  const receipt = { ...intent, state: notApplied ? 'NOT_APPLIED' : 'UNKNOWN',
    updatedAt: Date.now(), error: String(ack?.error || 'SIMPLE_RELAY_ACK_INVALID').slice(0, 200) };
  await writeSimpleRelayV0Receipt(request.operationId, receipt);
  return { ok: false, ambiguous: !notApplied, receipt };
}

async function returnSimpleRelayV0(message, requestId) {
  const state = await loadState();
  const sourceOperationId = SimpleRelayV0.operationId(message.sourceOperationId);
  const returnOperationId = SimpleRelayV0.operationId(message.operationId || requestId);
  const receipts = await readSimpleRelayV0Receipts();
  const source = receipts[sourceOperationId];
  if (!source || source.state !== 'SUBMITTED' || source.from !== SimpleRelayV0.ROLE.MANAGER
      || source.to !== SimpleRelayV0.ROLE.WORKER || !Number.isInteger(source.beforeAssistantCount)) {
    throw new Error('SIMPLE_RELAY_SOURCE_RECEIPT_NOT_RETURNABLE');
  }
  const route = SimpleRelayV0.targetFor(state.simpleRelayV0Binding, SimpleRelayV0.ROLE.WORKER);
  const fingerprint = await relaySha256(JSON.stringify([
    sourceOperationId, source.textSha256, source.beforeAssistantCount,
    route.sourceConversationKey, route.targetConversationKey,
  ]));
  const existing = receipts[returnOperationId];
  if (existing) {
    if (existing.fingerprint !== fingerprint) throw new Error('SIMPLE_RELAY_OPERATION_ID_REUSE_MISMATCH');
    if (existing.state === 'SUBMITTED') return { ok: true, replayed: true, receipt: existing };
    throw new Error('SIMPLE_RELAY_PRIOR_EFFECT_UNRESOLVED');
  }
  const tabs = simpleRelayV0TabsForBinding(await getChatTabs(), state.simpleRelayV0Binding);
  const intent = {
    version: 0, kind: 'RETURN', operationId: returnOperationId, fingerprint,
    sourceOperationId, from: route.from, to: route.to,
    targetConversationKey: route.targetConversationKey, state: 'INTENT', updatedAt: Date.now(),
  };
  await writeSimpleRelayV0Receipt(returnOperationId, intent);
  const read = await sendToChatTab(tabs.worker.id, {
    type: 'relay:simpleReadReply', conversationKey: route.sourceConversationKey,
    afterAssistantCount: source.beforeAssistantCount, relayId: sourceOperationId,
  });
  if (read?.ok !== true || read.conversationKey !== route.sourceConversationKey
      || typeof read.responseText !== 'string' || !read.responseText) {
    const receipt = { ...intent, state: 'NOT_APPLIED', updatedAt: Date.now(),
      error: String(read?.error || 'SIMPLE_RELAY_REPLY_READ_UNVERIFIED').slice(0, 200) };
    await writeSimpleRelayV0Receipt(returnOperationId, receipt);
    return { ok: false, ambiguous: false, receipt };
  }
  const responseText = read.responseText;
  const captured = { ...intent, state: 'REPLY_CAPTURED', responseSha256: await relaySha256(responseText),
    responseLength: responseText.length, updatedAt: Date.now() };
  await writeSimpleRelayV0Receipt(returnOperationId, captured);
  let ack;
  try {
    ack = await sendToChatTab(tabs.manager.id, {
      type: 'relay:simpleExecute', relayId: returnOperationId,
      conversationKey: route.targetConversationKey, text: responseText,
    });
  } catch (error) {
    const receipt = { ...captured, state: 'UNKNOWN', updatedAt: Date.now(),
      error: String(error?.message || error || 'SIMPLE_RELAY_RETURN_TRANSPORT_UNKNOWN').slice(0, 200) };
    await writeSimpleRelayV0Receipt(returnOperationId, receipt);
    return { ok: false, ambiguous: true, receipt };
  }
  if (ack?.ok === true && ack.submitted === true && ack.conversationKey === route.targetConversationKey) {
    const receipt = { ...captured, state: 'SUBMITTED', tabId: tabs.manager.id,
      windowId: tabs.manager.windowId, updatedAt: Date.now() };
    await writeSimpleRelayV0Receipt(returnOperationId, receipt);
    return { ok: true, receipt };
  }
  const notApplied = ack?.effectState === 'NOT_APPLIED' || ack?.submitted === false;
  const receipt = { ...captured, state: notApplied ? 'NOT_APPLIED' : 'UNKNOWN', updatedAt: Date.now(),
    error: String(ack?.error || 'SIMPLE_RELAY_RETURN_ACK_INVALID').slice(0, 200) };
  await writeSimpleRelayV0Receipt(returnOperationId, receipt);
  return { ok: false, ambiguous: !notApplied, receipt };
}


