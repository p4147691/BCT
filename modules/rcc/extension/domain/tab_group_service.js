// Tab-group mutations are independently receipted. They intentionally use
// Chrome's native groups across ordinary browser tabs; message delivery stays
// in the separate ChatGPT-only command path.
const TAB_GROUP_RECEIPTS_KEY = 'tabGroupReceiptsV1';
let tabGroupMutation = Promise.resolve();

function tabGroupOperationId(value) {
  const id = String(value || '').trim();
  if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(id)) throw new Error('TAB_GROUP_OPERATION_ID_INVALID');
  return id;
}

async function readTabGroupReceipts() {
  const data = await stateRepository.getLocal(TAB_GROUP_RECEIPTS_KEY);
  return data[TAB_GROUP_RECEIPTS_KEY] && typeof data[TAB_GROUP_RECEIPTS_KEY] === 'object'
    ? data[TAB_GROUP_RECEIPTS_KEY] : {};
}

async function writeTabGroupReceipt(operationId, receipt) {
  const task = tabGroupMutation.then(async () => {
    const receipts = await readTabGroupReceipts();
    receipts[operationId] = { ...receipt, operationId, updatedAt: Date.now() };
    const retained = Object.entries(receipts).sort((a, b) => Number(b[1]?.updatedAt || 0)
      - Number(a[1]?.updatedAt || 0)).slice(0, 64);
    await stateRepository.setLocal({ [TAB_GROUP_RECEIPTS_KEY]: Object.fromEntries(retained) });
    return receipts[operationId];
  });
  tabGroupMutation = task.catch(() => {});
  return task;
}

async function tabGroupEndpoint(message) {
  await endpointSessionReady;
  const state = await loadState();
  const instanceId = String(message?.instanceId || '').trim();
  const sessionId = String(message?.sessionId || '').trim();
  if (instanceId !== String(state.settings?.instanceId || '')) throw new Error('TAB_GROUP_INSTANCE_ID_MISMATCH');
  if (!sessionId || sessionId !== endpointSessionId) throw new Error('TAB_GROUP_SESSION_ID_MISMATCH');
  return { instanceId, sessionId };
}

function tabGroupIntent(command, message, endpoint, operationId) {
  const common = { command, operationId, sessionId: endpoint.sessionId };
  if (command === 'create-tab-group') return { ...common, tabIds: message.tabIds,
    title: message.title, color: message.color, collapsed: message.collapsed };
  if (command === 'add-tab-to-group' || command === 'remove-tab-from-group') {
    return { ...common, groupId: message.groupId, tabId: message.tabId };
  }
  if (command === 'move-tab-group') return { ...common, groupId: message.groupId,
    windowId: message.windowId, targetWindowId: message.targetWindowId, index: message.index };
  return { ...common, groupId: message.groupId, title: message.title,
    color: message.color, collapsed: message.collapsed };
}

async function mutateTabGroup(command, message) {
  const operationId = tabGroupOperationId(message?.operationId || message?.requestId);
  const endpoint = await tabGroupEndpoint(message);
  const intent = tabGroupIntent(command, message, endpoint, operationId);
  const fingerprint = RccBrowserTabGroupContract.fingerprint(intent);
  const existing = (await readTabGroupReceipts())[operationId];
  if (existing) {
    if (existing.command !== command || existing.fingerprint !== fingerprint) {
      throw new Error('TAB_GROUP_OPERATION_ID_REUSE_MISMATCH');
    }
    return { ...existing.result, replayed: true };
  }
  const result = await getTabGroupAdapter().apply(intent);
  await writeTabGroupReceipt(operationId, { command, fingerprint, result });
  return result;
}

async function readTabGroups(message, groupId = null) {
  await tabGroupEndpoint(message);
  const adapter = getTabGroupAdapter();
  return groupId === null ? { ok: true, groups: await adapter.list() }
    : { ok: true, group: await adapter.get(groupId) };
}

// This is an observation, not a delivery acknowledgement.  It deliberately
// does not infer which prior user turn the visible answer belongs to.
async function readLatestAssistant(message) {
  await tabGroupEndpoint(message);
  const tabId = Number(message?.tabId);
  const windowId = Number(message?.windowId);
  const conversationKey = String(message?.conversationKey || '').trim().toLowerCase();
  if (!Number.isSafeInteger(tabId) || tabId < 1 || !Number.isSafeInteger(windowId) || windowId < 1
      || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(conversationKey)) {
    throw new Error('READ_LATEST_ASSISTANT_IDENTITY_INVALID');
  }
  const tab = await browserGateway.getExactTab(tabId);
  const liveKey = RelayCore.conversationKey(String(tab?.url || '')).toLowerCase();
  if (!browserGateway.isChatTab(tab) || Number(tab.windowId) !== windowId || liveKey !== conversationKey) {
    return { ok: false, observationState: 'NOT_APPLIED', error: 'READ_LATEST_ASSISTANT_IDENTITY_MISMATCH' };
  }
  const result = await browserGateway.sendWithReceiver(tabId, {
    type: 'relay:readLatestAssistant', conversationKey,
  });
  if (!result || result.ok !== true || String(result.conversationKey || '').toLowerCase() !== conversationKey) {
    return { ok: false, observationState: 'UNKNOWN', error: String(result?.error || 'READ_LATEST_ASSISTANT_UNAVAILABLE') };
  }
  return { ...result, tabId, windowId, conversationKey };
}
