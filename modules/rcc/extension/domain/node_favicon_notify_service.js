// Exact-tab notification only. No label content, page edits, timers, or new watcher.
const nodeFaviconNotifications = new Map();
async function notifyNodeFaviconChanged(message, operationId) {
  const eventId = message.eventId;
  const uuid = String(message.conversationKey || '').toLowerCase();
  const tabId = message.tabId;
  const windowId = message.windowId;
  const sessionId = String(message.sessionId || '');
  const fail = (error, effectState = 'NOT_APPLIED') => ({
    ok: false, effectState, error,
    operationId, eventId, conversationKey: uuid, tabId, windowId,
    sessionId, instanceId: String(message.instanceId || '')
  });
  if (!Number.isSafeInteger(eventId) || eventId <= 0
      || !/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(uuid)
      || !Number.isSafeInteger(tabId) || tabId <= 0
      || !Number.isSafeInteger(windowId) || windowId <= 0
      || !/^[a-f0-9]{32}$/.test(sessionId))
    return fail('NODE_FAVICON_ARGUMENT_INVALID');
  const state = await loadState();
  const instanceId = String(state.settings.instanceId || '');
  if (instanceId !== String(message.instanceId || '') || sessionId !== endpointSessionId)
    return fail('NODE_FAVICON_INSTANCE_SESSION_MISMATCH');
  const identity = [instanceId, sessionId, tabId, windowId, uuid, eventId].join(':');
  const old = nodeFaviconNotifications.get(eventId);
  if (old && old !== identity) return fail('NODE_FAVICON_EVENT_ID_COLLISION');
  const before = await browserGateway.getExactTab(tabId).catch(() => null);
  if (!before || !isChatTab(before) || before.windowId !== windowId
      || RelayCore.conversationKey(String(before.url || '')) !== uuid)
    return fail('NODE_FAVICON_TARGET_MISMATCH');
  const peers = (await getChatTabs()).filter((tab) =>
    RelayCore.conversationKey(String(tab.url || '')) === uuid);
  if (peers.length !== 1 || peers[0].id !== tabId)
    return fail('NODE_FAVICON_AMBIGUOUS_UUID');
  if (old === identity)
    return { ok: true, operationId, eventId, tabId, windowId, conversationKey: uuid,
      sessionId, instanceId, state: 'DELIVERED', duplicate: true };
  let content;
  try {
    content = await browserGateway.sendWithReceiver(tabId, {
      type: 'relay:nodeLabelNotify', eventId, conversationKey: uuid,
    });
  } catch (_) {
    return fail('NODE_FAVICON_CONTENT_DELIVERY_UNKNOWN', 'UNKNOWN');
  }
  if (!content || content.ok !== true || content.eventId !== eventId
      || content.conversationKey !== uuid)
    return fail('NODE_FAVICON_CONTENT_ACK_UNKNOWN', 'UNKNOWN');
  const after = await browserGateway.getExactTab(tabId).catch(() => null);
  if (!after || after.windowId !== windowId
      || RelayCore.conversationKey(String(after.url || '')) !== uuid)
    return fail('NODE_FAVICON_POSTSEND_TAB_CHANGED', 'UNKNOWN');
  // The Core Operation is the durable dedupe authority; local cache is optimization.
  nodeFaviconNotifications.set(eventId, identity);
  if (nodeFaviconNotifications.size > 1024) {
    nodeFaviconNotifications.delete(nodeFaviconNotifications.keys().next().value);
  }
  return { ok: true, operationId, eventId, tabId, windowId, conversationKey: uuid,
    sessionId, instanceId, state: 'DELIVERED' };
}
