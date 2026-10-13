const CHAT_URLS = ['https://chatgpt.com/*', 'https://chat.openai.com/*'];

const CONTROL = 'CONTROL';

const NATIVE_HOST = 'com.ai_workspace_relay.host';

const RCC_BACKGROUND_BUILD_ID = '2026-10-10-rcc-e2e-recovery-v1';

const RELAY_RESULT_RECEIPTS_KEY = 'relayResultReceiptsV1';

let relayReceiptMutationChain = Promise.resolve();

let nativePort = null;

let nativeReconnectTimer = null;

const endpointPresence = new Map();

const ENDPOINT_SESSION_STORAGE_KEY = 'rccEndpointSessionIdV1';
let endpointSessionId = '';
const endpointSessionReady = (async () => {
  try {
    const data = await chrome.storage.session.get([ENDPOINT_SESSION_STORAGE_KEY]);
    let sessionId = String(data?.[ENDPOINT_SESSION_STORAGE_KEY] || '').trim();
    if (!/^[a-f0-9]{32}$/i.test(sessionId)) {
      sessionId = crypto.randomUUID().replaceAll('-', '');
      await chrome.storage.session.set({ [ENDPOINT_SESSION_STORAGE_KEY]: sessionId });
    }
    endpointSessionId = sessionId;
  } catch (_) {
    endpointSessionId = crypto.randomUUID().replaceAll('-', '');
  }
  return endpointSessionId;
})();



const relayNetworkRequests = new Map();

function relayNetworkUrlLooksRelevant(url) {

  try {

    const path = new URL(String(url || '')).pathname.toLowerCase();

    if (/\/conversation\/prepare(?:\/|$)/.test(path)) return false;

    return /^\/backend-api\/(?:f\/)?conversation(?:$|\/)/.test(path);

  } catch (_) { return false; }

}

async function findPendingRelayForNetwork(tabId) {

  const state = await loadState();

  const now = Date.now();

  const candidates = Object.entries(state.pending || {}).filter(([, item]) =>

    Number(item?.tabId) === Number(tabId) && !item?.networkRequestId &&

    now - Number(item?.createdAt || 0) >= 0 && now - Number(item?.createdAt || 0) <= 20000

  ).sort((a,b) => Number(b[1]?.createdAt || 0) - Number(a[1]?.createdAt || 0));

  return { state, match: candidates[0] || null };

}



async function loadState() {

  const data = await chrome.storage.local.get(['registrations', 'settings', 'pending', 'results', 'processed', 'operations', RELAY_RESULT_RECEIPTS_KEY]);

  const settings = data.settings || {};

  let settingsDirty = false;

  if (!settings.token) {

    settings.token = crypto.randomUUID();

    settings.armed = false;

    settings.budget = 0;

    settingsDirty = true;

  }

  if (!settings.instanceId) {

    settings.instanceId = crypto.randomUUID().replaceAll('-', '');

    settingsDirty = true;

  }

  if (settingsDirty) await chrome.storage.local.set({ settings });

  return {

    registrations: data.registrations || {},

    settings,

    pending: data.pending || {},

    results: data.results || [],

    processed: data.processed || [],

    operations: data.operations || {},

    resultReceipts: data[RELAY_RESULT_RECEIPTS_KEY] || {}

  };

}

function boundedRelayResultPayload(result) {
  const reply = String(result?.reply || '');
  if (reply.length > 1048576) throw new Error('RELAY_RESULT_TOO_LARGE');
  return {
    ok: result?.ok === true,
    reply,
    error: String(result?.error || '').slice(0, 1000),
    ambiguous: result?.ambiguous === true
  };
}

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
    ambiguous: payload.ambiguous === true,
    fingerprint: String(receipt.dispatchFingerprint || ''),

    messageHash: String(receipt.messageHash || ''),
    tabId: Number(receipt.tabId) || null,
    conversationKey: String(receipt.conversationKey || ''),
    resultHash: String(receipt.resultHash || ''),
    resultState: String(receipt.resultState || ''),
    ackState: String(receipt.ackState || ''),
    receiverAckState: String(receipt.receiverAckState || ''),
    returnState: String(receipt.returnState || ''),
    at: Number(receipt.completedAt || 0) || null
  };
}

function withRelayReceiptMutation(work) {
  const next = relayReceiptMutationChain.catch(() => {}).then(work);
  relayReceiptMutationChain = next.catch(() => {});
  return next;
}

async function persistDurableResultReceipt(relayId, pending, result) {
  const routeId = String(relayId || '').trim();
  if (!routeId) throw new Error('RELAY_ID_REQUIRED');
  const resultPayload = boundedRelayResultPayload(result);
  const resultHash = await relaySha256(JSON.stringify(resultPayload));
  return withRelayReceiptMutation(async () => {
    const data = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
    const receipts = { ...(data[RELAY_RESULT_RECEIPTS_KEY] || {}) };
    const existing = receipts[routeId] || null;
    if (existing) {
      if (String(existing.resultHash || '') !== resultHash) throw new Error('RELAY_RESULT_CONFLICT');
      return { receipt: existing, duplicate: true };
    }
    if (!pending) throw new Error('Unknown relay result');
    const completedAt = Date.now();
    const receipt = {
      version: 1,
      routeId,
      messageHash: String(pending.messageHash || pending.fingerprint || ''),

      dispatchFingerprint: String(pending.fingerprint || ''),
      from: String(pending.fromNode || pending.source || ''),
      to: String(pending.to || ''),
      targetBindingReceipt: String(pending.targetBindingReceipt || ''),
      submitState: pending.submitUnknown === true ? 'SUBMIT_UNKNOWN' :
        pending.deliveryConfirmed === true ? 'SUBMITTED_CONFIRMED' : 'SUBMIT_NOT_STARTED',
      resultState: 'RESULT_PERSISTED',
      resultHash,
      resultPayload,
      tabId: Number(pending.tabId) || null,
      conversationKey: String(pending.conversationKey || ''),
      createdAt: Number(pending.createdAt || 0) || null,
      completedAt,
      ackState: 'UNACKED',
      acknowledgedAt: null,
      receiverAckState: (pending.returnToRole || pending.returnToControl) ? 'PENDING' : 'NOT_REQUESTED',
      receiverAcknowledgedAt: null,
      returnState: (pending.returnToRole || pending.returnToControl) ? 'PENDING' : 'NOT_REQUESTED',
      returnedAt: null,
      returnToRole: String(pending.returnToRole || ''),
      returnToControl: pending.returnToControl === true
    };
    receipts[routeId] = receipt;
    await chrome.storage.local.set({ [RELAY_RESULT_RECEIPTS_KEY]: receipts });
    const verified = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
    const stored = verified[RELAY_RESULT_RECEIPTS_KEY]?.[routeId] || null;
    if (!stored || String(stored.resultHash || '') !== resultHash) throw new Error('RELAY_RESULT_PERSIST_VERIFY_FAILED');
    return { receipt: stored, duplicate: false };
  });
}

function isRecoverableCaptureResult(payload) {
  if (!payload || payload.ok === true) return false;
  const error = String(payload.error || '');
  return /RELAY_NETWORK_SIGNAL_TIMEOUT|RELAY_FINAL_DOM_UNKNOWN:ASSISTANT_RESPONSE_AMBIGUOUS|net::ERR_FAILED|RELAY_FINAL_DOM_NOT_READY/i.test(error);
}

async function replaceRecoverableResultReceipt(relayId, recoveredResult) {
  const routeId = String(relayId || '').trim();
  if (!routeId) throw new Error('RELAY_ID_REQUIRED');
  const nextPayload = boundedRelayResultPayload(recoveredResult);
  if (nextPayload.ok !== true || !String(nextPayload.reply || '').trim()) throw new Error('RELAY_RECOVERY_RESULT_INVALID');
  const nextHash = await relaySha256(JSON.stringify(nextPayload));
  return withRelayReceiptMutation(async () => {
    const data = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
    const receipts = { ...(data[RELAY_RESULT_RECEIPTS_KEY] || {}) };
    const receipt = receipts[routeId] || null;
    if (!receipt || receipt.resultState !== 'RESULT_PERSISTED') throw new Error('RELAY_RESULT_NOT_FOUND');
    if (receipt.ackState === 'ACKED' || receipt.returnState === 'DELIVERED') throw new Error('RELAY_RECOVERY_RESULT_ALREADY_FINAL');
    if (!isRecoverableCaptureResult(receipt.resultPayload)) throw new Error('RELAY_RECOVERY_RESULT_NOT_CAPTURE_ERROR');
    const updated = {
      ...receipt,
      priorResultHash: String(receipt.resultHash || ''),
      priorResultError: String(receipt.resultPayload?.error || ''),
      recoveryCorrectedAt: Date.now(),
      resultHash: nextHash,
      resultPayload: nextPayload,
      completedAt: Date.now()
    };
    receipts[routeId] = updated;
    await chrome.storage.local.set({ [RELAY_RESULT_RECEIPTS_KEY]: receipts });
    const verified = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
    const stored = verified[RELAY_RESULT_RECEIPTS_KEY]?.[routeId] || null;
    if (!stored || String(stored.resultHash || '') !== nextHash) throw new Error('RELAY_RECOVERY_RESULT_VERIFY_FAILED');
    return stored;
  });
}

async function markDurableResultReturned(relayId, stateValue) {
  return withRelayReceiptMutation(async () => {
    const routeId = String(relayId || '');
    const data = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
    const receipts = { ...(data[RELAY_RESULT_RECEIPTS_KEY] || {}) };
    const receipt = receipts[routeId] || null;
    if (!receipt) throw new Error('RELAY_RESULT_NOT_FOUND');
    const returnState = String(stateValue || 'DELIVERED');
    const updated = { ...receipt, returnState,
      returnedAt: returnState === 'DELIVERED' ? Date.now() : receipt.returnedAt || null };
    receipts[routeId] = updated;
    await chrome.storage.local.set({ [RELAY_RESULT_RECEIPTS_KEY]: receipts });
    return updated;
  });
}

async function acknowledgeDurableResultReceipt(relayId) {
  const routeId = String(relayId || '').trim();
  if (!routeId) throw new Error('RELAY_ID_REQUIRED');
  return withRelayReceiptMutation(async () => {
    const data = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
    const receipts = { ...(data[RELAY_RESULT_RECEIPTS_KEY] || {}) };
    const receipt = receipts[routeId] || null;
    if (!receipt) throw new Error('RELAY_RESULT_NOT_FOUND');
    if (receipt.ackState === 'ACKED') return { receipt, duplicate: true };
    const updated = { ...receipt, ackState: 'ACKED', acknowledgedAt: Date.now() };
    receipts[routeId] = updated;
    await chrome.storage.local.set({ [RELAY_RESULT_RECEIPTS_KEY]: receipts });
    const verified = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
    const stored = verified[RELAY_RESULT_RECEIPTS_KEY]?.[routeId] || null;
    if (!stored || stored.ackState !== 'ACKED') throw new Error('RELAY_RESULT_ACK_VERIFY_FAILED');
    return { receipt: stored, duplicate: false };
  });
}





async function markDurableReceiverDelivered(relayId) {
  const routeId = String(relayId || '').trim();
  if (!routeId) throw new Error('RELAY_ID_REQUIRED');
  return withRelayReceiptMutation(async () => {
    const data = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
    const receipts = { ...(data[RELAY_RESULT_RECEIPTS_KEY] || {}) };
    const receipt = receipts[routeId] || null;
    if (!receipt) throw new Error('RELAY_RESULT_NOT_FOUND');
    if (receipt.returnState === 'DELIVERED' && receipt.receiverAckState === 'ACKED') {
      return { receipt, duplicate: true };
    }
    const now = Date.now();
    const updated = {
      ...receipt,
      returnState: 'DELIVERED',
      returnedAt: receipt.returnedAt || now,
      receiverAckState: 'ACKED',
      receiverAcknowledgedAt: receipt.receiverAcknowledgedAt || now,
    };
    receipts[routeId] = updated;
    await chrome.storage.local.set({ [RELAY_RESULT_RECEIPTS_KEY]: receipts });
    const verified = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
    const stored = verified[RELAY_RESULT_RECEIPTS_KEY]?.[routeId] || null;
    if (!stored || stored.returnState !== 'DELIVERED' || stored.receiverAckState !== 'ACKED') {
      throw new Error('RELAY_RETURN_ACK_VERIFY_FAILED');
    }
    return { receipt: stored, duplicate: false };
  });
}

async function beginDurableReceiverDelivery(relayId) {
  const routeId = String(relayId || '').trim();
  if (!routeId) throw new Error('RELAY_ID_REQUIRED');
  return withRelayReceiptMutation(async () => {
    const data = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
    const receipts = { ...(data[RELAY_RESULT_RECEIPTS_KEY] || {}) };
    const receipt = receipts[routeId] || null;
    if (!receipt) throw new Error('RELAY_RESULT_NOT_FOUND');
    if (receipt.returnState === 'DELIVERED' && receipt.receiverAckState === 'ACKED') {
      return { receipt, started: false, delivered: true };
    }
    if (receipt.returnState === 'DELIVERING') {
      return { receipt, started: false, delivered: false, inFlight: true };
    }
    const updated = { ...receipt, returnState: 'DELIVERING', returnAttemptedAt: Date.now() };
    receipts[routeId] = updated;
    await chrome.storage.local.set({ [RELAY_RESULT_RECEIPTS_KEY]: receipts });
    return { receipt: updated, started: true, delivered: false };
  });
}

async function resetDurableReceiverDelivery(relayId) {
  const routeId = String(relayId || '').trim();
  if (!routeId) return null;
  return withRelayReceiptMutation(async () => {
    const data = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
    const receipts = { ...(data[RELAY_RESULT_RECEIPTS_KEY] || {}) };
    const receipt = receipts[routeId] || null;
    if (!receipt || receipt.returnState !== 'DELIVERING') return receipt;
    const updated = { ...receipt, returnState: 'PENDING', returnAttemptedAt: null };
    receipts[routeId] = updated;
    await chrome.storage.local.set({ [RELAY_RESULT_RECEIPTS_KEY]: receipts });
    return updated;
  });
}

async function confirmDurableReceiverDelivery(sender, relayId) {
  const routeId = String(relayId || '').trim();
  if (!routeId) throw new Error('RELAY_ID_REQUIRED');
  const tab = sender?.tab;
  if (!isChatTab(tab) || tab?.id == null) throw new Error('RELAY_RETURN_ACK_SOURCE_NOT_CHAT_TAB');
  const data = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
  const receipt = (data[RELAY_RESULT_RECEIPTS_KEY] || {})[routeId] || null;
  if (!receipt) throw new Error('RELAY_RESULT_NOT_FOUND');
  const returnRole = String(receipt.returnToRole || '').trim()
    || (receipt.returnToControl === true ? CONTROL : '');
  if (!returnRole) throw new Error('RELAY_RETURN_TARGET_NOT_REQUESTED');
  const registration = await resolveRegistration(returnRole);
  const conversationKey = RelayCore.conversationKey(tab.url || '');
  if (Number(registration.tabId) !== Number(tab.id)
      || !conversationKey
      || String(registration.conversationKey || '') !== conversationKey) {
    throw new Error('RELAY_RETURN_ACK_IDENTITY_MISMATCH');
  }
  return markDurableReceiverDelivered(routeId);
}

async function returnPersistedResult(relayId, pending, receipt) {
  if (!receipt || String(receipt.resultState || '') !== 'RESULT_PERSISTED') {
    throw new Error('RELAY_RESULT_NOT_PERSISTED');
  }
  const returnRole = String(pending?.returnToRole || receipt.returnToRole || '').trim()
    || ((pending?.returnToControl === true || receipt.returnToControl === true) ? CONTROL : '');
  if (!returnRole) {
    const finalState = await loadState();
    if (finalState.pending?.[relayId]) delete finalState.pending[relayId];
    await chrome.storage.local.set({ pending: finalState.pending });
    return { ok: true, returnState: 'NOT_REQUESTED', receiverAckState: 'NOT_REQUESTED', replayed: true };
  }
  if (receipt.returnState === 'DELIVERED' && receipt.receiverAckState === 'ACKED') {
    const finalState = await loadState();
    if (finalState.pending?.[relayId]) delete finalState.pending[relayId];
    await chrome.storage.local.set({ pending: finalState.pending });
    return { ok: true, returnState: 'DELIVERED', receiverAckState: 'ACKED', replayed: true };
  }
  const control = await resolveRegistration(returnRole);
  const claim = await beginDurableReceiverDelivery(relayId);
  if (claim.delivered === true) {
    return { ok: true, returnState: 'DELIVERED', receiverAckState: 'ACKED', replayed: true };
  }
  if (claim.inFlight === true || claim.started !== true) {
    return { ok: true, returnState: 'DELIVERING', receiverAckState: 'PENDING', inFlight: true };
  }
  const payload = receipt.resultPayload || {};
  const envelope = RelayCore.makeResultEnvelope(
    String(pending?.to || receipt.to || ''),
    relayId,
    payload.ok === true ? String(payload.reply || '') : `ERROR: ${String(payload.error || 'unknown')}`
  );
  let delivery;
  try {
    delivery = await sendToChatTab(control.tabId, { type: 'relay:deliver', relayId, text: envelope });
  } catch (error) {
    await resetDurableReceiverDelivery(relayId);
    throw error;
  }
  if (!delivery?.ok) {
    if (delivery?.inFlight !== true) await resetDurableReceiverDelivery(relayId);
    throw new Error(delivery?.error || 'RELAY_RETURN_DELIVERY_NOT_ACKED');
  }
  const acknowledged = await markDurableReceiverDelivered(relayId);
  const finalState = await loadState();
  if (finalState.pending?.[relayId]) delete finalState.pending[relayId];
  await chrome.storage.local.set({ pending: finalState.pending });
  return {
    ok: true,
    returnState: String(acknowledged.receipt?.returnState || ''),
    receiverAckState: String(acknowledged.receipt?.receiverAckState || ''),
    replayed: acknowledged.duplicate === true,
  };
}

// A completed worker result is durable before it ever reaches the manager.  If
// the manager is composing or generating, keep that result pending and retry
// only after the *same exact tab* reports that its composer is empty again.
// This is deliberately event-driven: it does not poll ChatGPT, overwrite a
// user draft, or redirect a result to a different role/tab.
async function retryPendingResultReturnForTab(tabId) {
  const state = await loadState();
  const pendingEntries = Object.entries(state.pending || {});
  const candidates = [];
  for (const [relayId, pending] of pendingEntries) {
    const receipt = state.resultReceipts?.[relayId];
    if (!receipt || String(receipt.resultState || '') !== 'RESULT_PERSISTED') continue;
    if (String(receipt.returnState || '') !== 'PENDING') continue;
    const returnRole = String(pending?.returnToRole || receipt.returnToRole || '').trim()
      || ((pending?.returnToControl === true || receipt.returnToControl === true) ? CONTROL : '');
    if (!returnRole) continue;
    const registration = state.registrations?.[returnRole];
    if (!registration || Number(registration.tabId) !== Number(tabId)) continue;
    candidates.push({ relayId, pending, receipt });
  }
  // One delivery per ready notification prevents a result burst from turning
  // into a prompt burst.  The next ready notification advances the queue.
  if (candidates.length === 0) return { attempted: false, pending: 0 };
  const candidate = candidates.sort((left, right) => String(left.relayId).localeCompare(String(right.relayId)))[0];
  try {
    const returned = await returnPersistedResult(candidate.relayId, candidate.pending, candidate.receipt);
    return { attempted: true, routeId: candidate.relayId, delivered: returned.returnState === 'DELIVERED',
      pending: candidates.length - (returned.returnState === 'DELIVERED' ? 1 : 0) };
  } catch (error) {
    // The receipt and pending route remain the recovery authority.  A later
    // ready event can retry; do not fabricate delivery or resend worker work.
    return { attempted: true, routeId: candidate.relayId, delivered: false,
      error: String(error?.message || error), pending: candidates.length };
  }
}

async function recordRelayNetworkCandidate(details) {

  if (!Number.isInteger(Number(details?.tabId)) || Number(details.tabId) < 0) return;

  const state = await loadState();

  const now = Date.now();

  const match = Object.entries(state.pending || {}).filter(([, item]) => Number(item?.tabId) === Number(details.tabId) && now - Number(item?.createdAt || 0) >= 0 && now - Number(item?.createdAt || 0) <= 20000).sort((a,b)=>Number(b[1]?.createdAt||0)-Number(a[1]?.createdAt||0))[0];

  if (!match) return;

  const [relayId,pending]=match; let path=''; try { path=new URL(String(details.url||'')).pathname.slice(0,300); } catch (_) {}

  const items=Array.isArray(pending.networkCandidates)?pending.networkCandidates:[];

  if (path && !items.some((item)=>item.path===path && item.method===String(details.method||''))) items.push({ path, method:String(details.method||''), type:String(details.type||''), at:now });

  pending.networkCandidates=items.slice(-12); state.pending[relayId]=pending; await chrome.storage.local.set({pending:state.pending});

}



async function correlateRelayNetworkStart(details) {

  await recordRelayNetworkCandidate(details);

  if (String(details?.method || '').toUpperCase() !== 'POST') return;

  if (!Number.isInteger(Number(details?.tabId)) || Number(details.tabId) < 0) return;

  if (!relayNetworkUrlLooksRelevant(details.url)) return;

  const { state, match } = await findPendingRelayForNetwork(details.tabId);

  if (!match) return;

  const [relayId, pending] = match;

  pending.networkRequestId = String(details.requestId || '');

  pending.networkStartedAt = Date.now();

  try { pending.networkPath = new URL(details.url).pathname.slice(0, 300); } catch (_) {}

  state.pending[relayId] = pending;

  await chrome.storage.local.set({ pending: state.pending });

  relayNetworkRequests.set(String(details.requestId || ''), { relayId, tabId: Number(details.tabId) });

  try { await sendToChatTab(Number(details.tabId), { type: 'relay:networkStarted', relayId }); } catch (_) {}

}

async function correlateRelayNetworkEnd(details, ok) {

  const requestId = String(details?.requestId || '');

  let tracked = relayNetworkRequests.get(requestId) || null;

  const state = await loadState();

  if (!tracked) {

    for (const [relayId, pending] of Object.entries(state.pending || {})) {

      if (String(pending?.networkRequestId || '') === requestId) { tracked = { relayId, tabId: Number(pending.tabId) }; break; }

    }

  }

  if (!tracked) return;

  const pending = state.pending?.[tracked.relayId];

  if (!pending) { relayNetworkRequests.delete(requestId); return; }

  pending.networkCompletedAt = Date.now();

  pending.networkOk = !!ok;

  if (!ok) pending.networkError = String(details?.error || 'NETWORK_REQUEST_FAILED').slice(0, 200);

  state.pending[tracked.relayId] = pending;

  await chrome.storage.local.set({ pending: state.pending });

  relayNetworkRequests.delete(requestId);

  try { await sendToChatTab(tracked.tabId, { type: 'relay:networkComplete', relayId: tracked.relayId, ok: !!ok, error: pending.networkError || '' }); } catch (_) {}

}



async function getChatTabs() {

  return chrome.tabs.query({ url: CHAT_URLS });

}

async function forEachChatTabBounded(tabsValue, worker, concurrency = 4) {
  const tabs = (Array.isArray(tabsValue) ? tabsValue : await getChatTabs())
    .filter(isChatTab)
    .filter((tab) => tab?.id != null);
  if (!tabs.length) return [];
  const width = Math.max(1, Math.min(Number(concurrency) || 1, tabs.length));
  let nextIndex = 0;
  const runners = Array.from({ length: width }, async () => {
    while (true) {
      const index = nextIndex;
      nextIndex += 1;
      if (index >= tabs.length) return;
      await worker(tabs[index]);
    }
  });
  await Promise.all(runners);
  return tabs;
}



function publicTab(tab) {

  return { id: tab.id, windowId: tab.windowId ?? null, title: tab.title || '', url: tab.url || '' };

}



function isChatTab(tab) {

  return !!(tab?.url && /^https:\/\/(chatgpt\.com|chat\.openai\.com)\//i.test(tab.url));

}



function endpointFromTab(tab, presence = 'OPEN', reason = '') {

  const url = String(tab?.url || '');

  return {

    tabId: tab?.id ?? null,

    windowId: tab?.windowId ?? null,

    conversationKey: RelayCore.conversationKey(url),

    title: String(tab?.title || ''),

    url,

    tabActive: tab?.active === true,

    presence,

    reason,

    observedAt: Date.now()

  };

}



function endpointComparable(endpoint) {

  const bounds = endpoint?.windowBounds && typeof endpoint.windowBounds === 'object' ? endpoint.windowBounds : {};

  return JSON.stringify([

    endpoint?.windowId ?? null,

    endpoint?.conversationKey || '',

    endpoint?.title || '',

    endpoint?.url || '',

    bounds.left ?? null, bounds.top ?? null, bounds.width ?? null, bounds.height ?? null,

    bounds.state || '', bounds.focused === true,

    endpoint?.telemetry ? JSON.stringify(endpoint.telemetry) : '',
    endpoint?.connection ? JSON.stringify(endpoint.connection) : ''

  ]);

}



async function attachEndpointWindowBounds(endpoint) {

  const windowId = Number(endpoint?.windowId);

  if (!Number.isInteger(windowId)) return endpoint;

  try {

    const win = await chrome.windows.get(windowId);

    endpoint.windowBounds = {

      left: Number(win?.left) || 0, top: Number(win?.top) || 0,

      width: Number(win?.width) || 0, height: Number(win?.height) || 0,

      state: String(win?.state || ''), focused: win?.focused === true,

      activeTab: endpoint?.tabActive === true

    };

  } catch (_) {}

  return endpoint;

}



async function endpointFromTabWithActivity(tab, presence = 'OPEN', reason = '') {

  const endpoint = endpointFromTab(tab, presence, reason);

  if (presence !== 'OPEN' || tab?.id == null) return endpoint;

  await attachEndpointWindowBounds(endpoint);

  try {

    const probe = await chrome.tabs.sendMessage(tab.id, { type: 'relay:activityProbe' });

    endpoint.generating = !!probe?.generating;

    endpoint.telemetry = probe?.telemetry && typeof probe.telemetry === 'object' ? probe.telemetry : null;
    endpoint.connection = probe?.connection && typeof probe.connection === 'object' ? probe.connection : null;

  } catch (_) {

    const previous = endpointPresence.get(tab.id);

    if (typeof previous?.generating === 'boolean') endpoint.generating = previous.generating;

    if (previous?.telemetry && typeof previous.telemetry === 'object') endpoint.telemetry = previous.telemetry;
    if (previous?.connection && typeof previous.connection === 'object') endpoint.connection = previous.connection;

  }

  return endpoint;

}



async function captureEndpointSnapshot(reason = 'snapshot', tabsValue = null) {

  const tabs = Array.isArray(tabsValue) ? tabsValue : await getChatTabs();

  const previous = new Map(endpointPresence);

  endpointPresence.clear();

  const endpoints = await Promise.all(tabs.filter(isChatTab).map((tab) => endpointFromTabWithActivity(tab, 'OPEN', reason)));

  for (const endpoint of endpoints) {

    const prior = previous.get(endpoint.tabId);

    if (typeof endpoint.generating !== 'boolean' && typeof prior?.generating === 'boolean') endpoint.generating = prior.generating;

    if (prior?.telemetry && typeof prior.telemetry === 'object') endpoint.telemetry = { ...prior.telemetry, ...(endpoint.telemetry && typeof endpoint.telemetry === 'object' ? endpoint.telemetry : {}) };

    endpointPresence.set(endpoint.tabId, endpoint);

  }

  return endpoints;

}



async function postEndpointPresence(mode, endpoints, reason) {

  await endpointSessionReady;
  const state = await loadState();

  postNative({

    type: 'host:endpoints',

    mode,

    instanceId: state.settings.instanceId,

    sessionId: endpointSessionId,

    observedAt: Date.now(),

    reason: String(reason || ''),

    endpoints

  });

}



async function publishEndpointSnapshot(reason = 'startup', tabsValue = null) {

  const endpoints = await captureEndpointSnapshot(reason, tabsValue);

  await postEndpointPresence('snapshot', endpoints, reason);

  return endpoints;

}



async function publishEndpointDelta(endpoint, reason) {

  await postEndpointPresence('delta', [endpoint], reason);

}



async function handleEndpointTabCreated(tab) {

  if (!isChatTab(tab)) return;

  const endpoint = endpointFromTab(tab, 'OPEN', 'created');

  endpointPresence.set(endpoint.tabId, endpoint);

  await publishEndpointDelta(endpoint, 'created');

}



async function handleEndpointTabUpdated(tabId, changeInfo, tab) {

  const previous = endpointPresence.get(tabId);

  if (!isChatTab(tab)) {

    if (!previous) return;

    endpointPresence.delete(tabId);

    await publishEndpointDelta({ ...previous, presence: 'OFFLINE', reason: 'navigated-away', observedAt: Date.now() }, 'navigated-away');

    return;

  }

  const next = endpointFromTab(tab, 'OPEN', previous ? 'updated' : 'opened');

  if (previous && endpointComparable(previous) === endpointComparable(next)) return;

  endpointPresence.set(tabId, next);

  await publishEndpointDelta(next, next.reason);

}



async function handleEndpointTabRemoved(tabId) {

  const previous = endpointPresence.get(tabId);

  if (!previous) return;

  endpointPresence.delete(tabId);

  await publishEndpointDelta({ ...previous, presence: 'OFFLINE', reason: 'removed', observedAt: Date.now() }, 'removed');

}



function isMissingReceiver(error) {

  return /Receiving end does not exist|Could not establish connection/i.test(String(error?.message || error || ''));

}



async function injectRelayReceiver(tabId) {

  const alreadyReady = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => globalThis.__RCC_RELAY_RECEIVER_READY__ === true,
  });
  if (alreadyReady?.[0]?.result === true) return;

  await chrome.scripting.executeScript({

    target: { tabId },

    files: ['relay_core.js', 'content.js', 'act_content.js', 'act_command_bridge.js']

  });

}



async function recoverCompletedReplyDirectlyFromTab(tabId, conversationKey, submittedText) {
  const tab = await chrome.tabs.get(tabId);
  if (!isChatTab(tab) || RelayCore.conversationKey(tab.url || '') !== String(conversationKey || '')) {
    throw new Error('RELAY_RECOVERY_DIRECT_IDENTITY_MISMATCH');
  }
  const injected = await chrome.scripting.executeScript({
    target: { tabId },
    args: [String(submittedText || '')],
    func: (submittedRaw) => {
      const normalize = (value) => String(value || '')
        .replace(/\u00a0/g, ' ')
        .replace(/[ \t]+\n/g, '\n')
        .replace(/\n[ \t]+/g, '\n')
        .replace(/[ \t]{2,}/g, ' ')
        .trim();
      const visible = (el) => !!(
        el && el.getClientRects().length > 0
        && getComputedStyle(el).visibility !== 'hidden'
        && getComputedStyle(el).display !== 'none'
      );
      const nodes = Array.from(document.querySelectorAll(
        '[data-turn-key],[data-content-search-turn-key],[data-testid^="conversation-turn-"]'
      ));
      const turns = [];
      const seen = new Set();
      for (const node of nodes) {
        const turn = node.matches('[data-turn-key]') ? node : (node.closest('[data-turn-key]') || node);
        if (seen.has(turn)) continue;
        seen.add(turn);
        turns.push(turn);
      }
      const submitted = normalize(submittedRaw);
      const submittedInline = normalize(submittedRaw.replace(/`([^`\r\n]+)`/g, '$1'));
      const compareCanonical = (value) => normalize(value).replace(/\s+/g, ' ');
      const submittedCanonical = compareCanonical(submitted);
      const submittedInlineCanonical = compareCanonical(submittedInline);
      const userText = (turn) => {
        const unit = turn.querySelector(
          '[data-message-author-role="user"],[data-content-search-unit-key$=":user"],[data-user-message-bubble="true"]'
        );
        if (!unit) return '';
        const content = unit.querySelector('[data-user-message-bubble="true"],[data-message-author-role="user"]') || unit;
        const clone = content.cloneNode(true);
        clone.querySelectorAll('button,[role="button"],[contenteditable="true"]').forEach((item) => item.remove());
        return normalize(clone.textContent || '');
      };
      const matches = turns.filter((turn) => {
        const rendered = userText(turn);
        if (!rendered) return false;
        const renderedCanonical = compareCanonical(rendered);
        return rendered === submitted
          || rendered === submittedInline
          || renderedCanonical === submittedCanonical
          || renderedCanonical === submittedInlineCanonical;
      });
      if (matches.length !== 1) {
        return { ok: false, error: matches.length > 1 ? 'RELAY_RECOVERY_DIRECT_TURN_AMBIGUOUS' : 'RELAY_RECOVERY_DIRECT_TURN_NOT_FOUND' };
      }
      const turn = matches[0];
      const turnState = String(
        turn.getAttribute('data-talvt-turn-state')
        || turn.querySelector('[data-talvt-turn-state]')?.getAttribute('data-talvt-turn-state')
        || ''
      ).trim().toLowerCase();
      if (/^(interrupted|cancelled|canceled|error|failed)$/.test(turnState)) {
        return { ok: false, error: 'RELAY_RECOVERY_DIRECT_INTERRUPTED' };
      }
      if (turn.querySelector(
        'button[data-testid="stop-button"],button[aria-label="Stop streaming"],button[aria-label="Stop"],button[aria-label="중지"],button[aria-label*="응답 중지"]'
      )) {
        return { ok: false, error: 'RELAY_RECOVERY_DIRECT_STILL_STREAMING' };
      }
      const assistantSelector = [
        '[data-message-author-role="assistant"]',
        '[data-content-search-unit-key$=":assistant"]',
        '[data-chatgpt-search-unit-key$=":assistant"]',
        '[data-markdown-text-style="assistant-message"]'
      ].join(',');
      const assistantNodes = Array.from(turn.querySelectorAll(assistantSelector)).filter(visible);
      const leafUnits = assistantNodes.filter((unit) =>
        !assistantNodes.some((other) => other !== unit && unit.contains(other))
      );
      if (!leafUnits.length) return { ok: false, error: 'RELAY_RECOVERY_DIRECT_ASSISTANT_MISSING' };
      const finalUnit = leafUnits[leafUnits.length - 1];
      const text = normalize(finalUnit.innerText || finalUnit.textContent || '');
      if (!text) return { ok: false, error: 'RELAY_RECOVERY_DIRECT_ASSISTANT_EMPTY' };
      const completeState = turnState === 'complete';
      const completionUiReady = !!turn.querySelector(
        'button[data-testid="copy-turn-action-button"],button[data-testid*="copy"],button[aria-label="Copy"],button[aria-label="복사"],button[aria-label="복사하기"]'
      );
      if (!completeState && !completionUiReady) {
        return { ok: false, error: 'RELAY_RECOVERY_DIRECT_FINAL_STATE_UNKNOWN' };
      }
      return { ok: true, reply: text };
    }
  });
  const result = injected?.[0]?.result || null;
  if (!result?.ok || !String(result.reply || '').trim()) {
    throw new Error(String(result?.error || 'RELAY_RECOVERY_DIRECT_FAILED'));
  }
  return { ok: true, recovered: true, recoveredReply: String(result.reply || ''), directDom: true };
}

async function sendToChatTab(tabId, message) {

  try {

    return await chrome.tabs.sendMessage(tabId, message);

  } catch (error) {

    if (!isMissingReceiver(error)) throw error;

    await injectRelayReceiver(tabId);

    await new Promise((resolve) => setTimeout(resolve, 100));

    return chrome.tabs.sendMessage(tabId, message);

  }

}


async function ensureRelayReceivers(tabsValue = null) {
  const repaired = [];
  const healthy = [];
  await forEachChatTabBounded(tabsValue, async (tab) => {
    try {
      await sendToChatTab(tab.id, { type: 'relay:probe' });
      healthy.push(tab.id);
    } catch (error) {
      repaired.push({ tabId: tab.id, error: String(error?.message || error || 'probe failed') });
    }
  });
  return { healthy, repaired };
}



async function resolveExactConversationCommand(message) {

  const conversationKey = String(message.conversationKey || '').trim();

  const sessionId = String(message.sessionId || '').trim();

  const tabId = Number(message.tabId);

  if (!/^[a-z0-9-]{8,64}$/i.test(conversationKey)) throw new Error('Invalid conversation key');

  if (!Number.isInteger(tabId) || tabId <= 0) throw new Error('Invalid tab id');

  if (sessionId && sessionId !== endpointSessionId) throw new Error('Endpoint session mismatch');

  const tab = await chrome.tabs.get(tabId);

  if (!isChatTab(tab) || RelayCore.conversationKey(tab.url || '') !== conversationKey) {

    throw new Error('Exact conversation target mismatch');

  }

  return tab;

}

async function resolveExactPendingCreatedTab(message) {

  await endpointSessionReady;

  const instanceId = String(message.instanceId || '').trim();

  const sessionId = String(message.sessionId || '').trim();

  const tabId = Number(message.tabId);

  const requestedWindowId = Number(message.windowId);

  const createOperationId = String(message.createOperationId || '').trim();

  const state = await loadState();

  if (!instanceId || instanceId !== String(state.settings.instanceId || '')) throw new Error('Endpoint instance mismatch');

  if (!sessionId || sessionId !== endpointSessionId) throw new Error('Endpoint session mismatch');

  if (!Number.isInteger(tabId) || tabId <= 0) throw new Error('Invalid tab id');

  const receipts = Object.entries(state.operations || {}).filter(([operationId, record]) =>

    (!createOperationId || operationId === createOperationId)

    && ['create-chat-tab', 'create-chat-window'].includes(record?.command)

    && record?.result?.state === 'PENDING_UNBOUND'

    && Number(record?.result?.tabId) === tabId

    && String(record?.result?.instanceId || '') === instanceId

    && Number(record?.result?.creationReceipt?.tabId) === tabId

    && Number(record?.result?.creationReceipt?.windowId) === Number(record?.result?.windowId)

    && String(record?.result?.creationReceipt?.instanceId || '') === instanceId

    && String(record?.result?.creationReceipt?.bindingState || '') === 'PENDING_UNBOUND');

  // A background reload intentionally rotates endpointSessionId while keeping
  // the same extension instance and Chrome tab.  The durable create receipt is
  // the authority for the still-blank tab; requiring its historical session
  // here makes automatic reconnect impossible.  The caller's current session
  // was already fenced above, and the live tab identity is verified below.

  if (receipts.length !== 1) throw new Error('PENDING_CREATE_RECEIPT_REQUIRED');

  const tab = await chrome.tabs.get(tabId);

  if (message.requireCurrentWindow === true && Number.isInteger(requestedWindowId) && requestedWindowId > 0

      && Number(tab?.windowId) !== requestedWindowId) throw new Error('PENDING_CREATED_WINDOW_IDENTITY_MISMATCH');

  const url = String(tab?.url || '');

  if (!isChatTab(tab) || RelayCore.conversationKey(url)

      || !/^https:\/\/(chatgpt\.com|chat\.openai\.com)\/?(?:[?#].*)?$/i.test(url)) {

    throw new Error('PENDING_CREATED_TAB_IDENTITY_MISMATCH');

  }

  return { tab, createOperationId: receipts[0][0] };

}

async function sendToCreatedTab(message) {

  const operationId = String(message.operationId || '').trim();

  const createOperationId = String(message.createOperationId || '').trim();

  const payloadText = String(message.text || '').slice(0, 12000);

  if (!operationId) throw new Error('Bootstrap send operation id required');

  if (!createOperationId) throw new Error('PENDING_CREATE_OPERATION_ID_REQUIRED');

  if (!payloadText) throw new Error('Bootstrap send text required');

  if (String(message.conversationKey || '').trim() || String(message.to || '').trim()) {

    throw new Error('BOOTSTRAP_SEND_BINDING_IDENTITY_FORBIDDEN');

  }

  const fingerprint = JSON.stringify([createOperationId, String(message.instanceId || ''),

    String(message.sessionId || ''), Number(message.tabId), Number(message.windowId), payloadText]);

  return runIdempotentOperation(operationId, 'send-to-created-tab', fingerprint, async () => {

    let resolved;

    try {

      resolved = await resolveExactPendingCreatedTab({ ...message, requireCurrentWindow: true });

      const state = await loadState();

      if (Object.values(state.registrations || {}).some((registration) =>

        Number(registration?.tabId) === Number(resolved.tab.id))) throw new Error('CONVERSATION_ALREADY_BOUND');

    } catch (error) {

      return { ok: false, state: 'NOT_APPLIED', operationId, createOperationId,

        tabId: Number(message.tabId) || null, windowId: Number(message.windowId) || null,

        error: String(error?.message || error || 'BOOTSTRAP_SEND_REJECTED') };

    }

    const state = await loadState();

    if (Object.entries(state.pending || {}).some(([pendingId, pending]) =>

      pendingId !== operationId && pending?.bootstrapCreatedTab === true

      && Number(pending?.tabId) === Number(resolved.tab.id))) {

      return { ok: false, state: 'NOT_APPLIED', operationId, createOperationId,

        tabId: Number(resolved.tab.id), windowId: Number(resolved.tab.windowId),

        error: 'BOOTSTRAP_SEND_ALREADY_PENDING' };

    }

    state.pending[operationId] = {

      to: '', tabId: Number(resolved.tab.id), windowId: Number(resolved.tab.windowId), conversationKey: '',

      source: 'ACT_CREATED_TAB_BOOTSTRAP', fromNode: '', messageHash: fingerprint,

      targetBindingReceipt: '', returnToControl: false, returnToRole: '', hostRequestId: '', fingerprint,

      createdAt: Date.now(), deliveryConfirmed: false, bootstrapCreatedTab: true,

      createOperationId, instanceId: String(state.settings.instanceId || ''), sessionId: endpointSessionId,

      submissionState: 'INTENT_RECORDED'

    };

    await chrome.storage.local.set({ pending: state.pending });

    let ack;

    try {

      ack = await sendToChatTab(resolved.tab.id, {

        type: 'relay:execute', relayId: operationId, text: payloadText, bootstrapCreatedTab: true

      });

    } catch (error) {

      const unknownState = await loadState();

      if (unknownState.pending?.[operationId]) {

        unknownState.pending[operationId].submitUnknown = true;

        unknownState.pending[operationId].submissionState = 'SUBMIT_UNKNOWN';

        unknownState.pending[operationId].lastTransportError = String(error?.message || error || 'SUBMIT_UNKNOWN').slice(0, 200);

        await chrome.storage.local.set({ pending: unknownState.pending });

      }

      return { ok: false, state: 'SUBMIT_UNKNOWN', operationId, createOperationId,

        tabId: Number(resolved.tab.id), windowId: Number(resolved.tab.windowId), error: 'SUBMIT_UNKNOWN' };

    }

    if (!ack?.ok || ack.submitted !== true) {

      const rejectedState = await loadState();

      if (ack?.deferred === true) {

        if (rejectedState.pending?.[operationId]) {

          rejectedState.pending[operationId].submitUnknown = true;

          rejectedState.pending[operationId].submissionState = 'SUBMIT_UNKNOWN';

          await chrome.storage.local.set({ pending: rejectedState.pending });

        }

        return { ok: false, state: 'SUBMIT_UNKNOWN', operationId, createOperationId,

          tabId: Number(resolved.tab.id), windowId: Number(resolved.tab.windowId), error: 'SUBMIT_DEFERRED_UNKNOWN' };

      }

      if (rejectedState.pending?.[operationId]) delete rejectedState.pending[operationId];

      await chrome.storage.local.set({ pending: rejectedState.pending });

      return { ok: false, state: 'NOT_APPLIED', operationId, createOperationId,

        tabId: Number(resolved.tab.id), windowId: Number(resolved.tab.windowId),

        error: String(ack?.error || 'BOOTSTRAP_SEND_NOT_APPLIED') };

    }

    const submittedState = await loadState();

    const pending = submittedState.pending?.[operationId];

    if (!pending) return { ok: false, state: 'SUBMIT_UNKNOWN', operationId, createOperationId,

      tabId: Number(resolved.tab.id), windowId: Number(resolved.tab.windowId), error: 'RELAY_PENDING_LOST_AFTER_ACCEPT' };

    const currentTab = await chrome.tabs.get(Number(resolved.tab.id));

    const capturedConversationKey = String(ack.conversationKey || RelayCore.conversationKey(currentTab?.url || '') || '');

    if (capturedConversationKey && RelayCore.conversationKey(currentTab?.url || '') !== capturedConversationKey) {

      pending.submitUnknown = true;

      pending.submissionState = 'SUBMIT_UNKNOWN';

      submittedState.pending[operationId] = pending;

      await chrome.storage.local.set({ pending: submittedState.pending });

      return { ok: false, state: 'SUBMIT_UNKNOWN', operationId, createOperationId,

        tabId: Number(resolved.tab.id), windowId: Number(resolved.tab.windowId), error: 'CONVERSATION_IDENTITY_MISMATCH' };

    }

    pending.deliveryConfirmed = true;

    pending.acceptedAt = Date.now();

    pending.submittedAt = Date.now();

    pending.submissionState = 'SUBMITTED';

    pending.conversationKey = capturedConversationKey;

    submittedState.pending[operationId] = pending;

    await chrome.storage.local.set({ pending: submittedState.pending });

    return { ok: true, state: 'SUBMITTED', operationId, createOperationId,

      tabId: Number(resolved.tab.id), windowId: Number(resolved.tab.windowId),

      conversationKey: capturedConversationKey, bindingState: 'PENDING_UNBOUND', responsePending: true };

  });

}

async function validateExactWindowId(windowIdValue) {

  const windowId = Number(windowIdValue);

  if (!Number.isInteger(windowId) || windowId <= 0) throw new Error('Invalid window id');

  try {

    const win = await chrome.windows.get(windowId);

    if (!win || Number(win.id) !== windowId) throw new Error('Invalid window id');

  } catch (_) {

    throw new Error('Invalid window id');

  }

  return windowId;

}

async function waitForBlankChatReady(tabId, timeoutMs = 8000) {

  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {

    const tab = await chrome.tabs.get(Number(tabId));

    const url = String(tab?.url || '');

    if (/^https:\/\/(chatgpt\.com|chat\.openai\.com)\/?(?:[?#].*)?$/i.test(url)

        && !RelayCore.conversationKey(url)) return tab;

    await new Promise((resolve) => setTimeout(resolve, 50));

  }

  throw new Error('Blank ChatGPT tab did not finish loading');

}

async function createChatTab(message) {

  const operationId = String(message.operationId || '').trim();

  if (!operationId) throw new Error('Create operation id required');

  if (String(message.conversationKey || '').trim()) throw new Error('CREATE_CHAT_TAB_CONVERSATION_KEY_FORBIDDEN');

  const hasWindowId = message.windowId !== undefined && message.windowId !== null && String(message.windowId) !== '';

  const requestedWindowId = hasWindowId ? await validateExactWindowId(message.windowId) : null;

  const fingerprint = JSON.stringify([requestedWindowId, 'https://chatgpt.com/']);

  return runIdempotentOperation(operationId, 'create-chat-tab', fingerprint, async () => {

    const state = await loadState();

    const receiptBase = {

      operationId,

      instanceId: String(state.settings.instanceId || ''),

      sessionId: endpointSessionId,

      conversationKey: '',

      pending: true,

      unbound: true

    };

    let created;

    try {

      const options = { url: 'https://chatgpt.com/', active: false };

      if (requestedWindowId !== null) options.windowId = requestedWindowId;

      created = await chrome.tabs.create(options);

    } catch (_) {

      return { ok: false, created: false, state: 'CREATE_UNKNOWN', ...receiptBase,

        tabId: null, windowId: requestedWindowId, error: 'CREATE_UNKNOWN' };

    }

    try {

      const tab = await waitForBlankChatReady(created.id);

      if (!isChatTab(tab) || RelayCore.conversationKey(tab.url || '')) throw new Error('Blank chat identity not ready');

      return { ok: true, created: true, state: 'PENDING_UNBOUND', ...receiptBase,

        tabId: tab.id, windowId: tab.windowId ?? requestedWindowId,

        creationReceipt: {

          tabId: tab.id,

          windowId: tab.windowId ?? requestedWindowId,

          instanceId: String(state.settings.instanceId || ''),

          sessionId: endpointSessionId,

          conversationKey: '',

          bindingState: 'PENDING_UNBOUND'

        } };

    } catch (_) {

      return { ok: false, created: true, state: 'CREATE_UNKNOWN', ...receiptBase,

        tabId: Number(created?.id) || null, windowId: created?.windowId ?? requestedWindowId,

        error: 'CREATE_UNKNOWN' };

    }

  });

}

async function waitForCreatedChatWindowReady(windowId, tabId, timeoutMs = 8000) {

  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {

    try {

      const win = await chrome.windows.get(Number(windowId));

      const tab = await chrome.tabs.get(Number(tabId));

      const url = String(tab?.url || '');

      if (Number(win?.id) === Number(windowId)

          && Number(tab?.windowId) === Number(windowId)

          && /^https:\/\/(chatgpt\.com|chat\.openai\.com)\/?(?:[?#].*)?$/i.test(url)

          && !RelayCore.conversationKey(url)) return { win, tab };

    } catch (_) {}

    await new Promise((resolve) => setTimeout(resolve, 50));

  }

  throw new Error('Created ChatGPT window did not become ready');

}

async function createChatWindow(message) {

  const operationId = String(message.operationId || '').trim();

  if (!operationId) throw new Error('Create window operation id required');

  if (String(message.conversationKey || '').trim()) throw new Error('CREATE_CHAT_WINDOW_CONVERSATION_KEY_FORBIDDEN');

  const fingerprint = JSON.stringify(['https://chatgpt.com/', 'normal']);

  return runIdempotentOperation(operationId, 'create-chat-window', fingerprint, async () => {

    const state = await loadState();

    const receiptBase = {

      operationId,

      instanceId: String(state.settings.instanceId || ''),

      sessionId: endpointSessionId,

      url: 'https://chatgpt.com/',

      conversationKey: '',

      bindingState: 'PENDING_UNBOUND'

    };

    let created;

    try {

      created = await chrome.windows.create({

        url: 'https://chatgpt.com/',

        type: 'normal',

        focused: true

      });

    } catch (_) {

      return { ok: false, created: false, state: 'CREATE_UNKNOWN', ...receiptBase,

        windowId: null, tabId: null, windowState: 'UNKNOWN', tabPresence: 'UNKNOWN',

        error: 'CREATE_UNKNOWN' };

    }

    const createdWindowId = Number(created?.id);

    let createdTab = null;

    try {

      if (!Number.isInteger(createdWindowId) || createdWindowId <= 0) {

        throw new Error('Created window identity missing');

      }

      createdTab = Array.isArray(created?.tabs) ? created.tabs[0] : null;

      if (!createdTab) {

        const createdTabs = await chrome.tabs.query({ windowId: createdWindowId });

        createdTab = createdTabs.find((tab) => /^https:\/\/(chatgpt\.com|chat\.openai\.com)\/?(?:[?#].*)?$/i.test(String(tab?.url || '')));

      }

      const createdTabId = Number(createdTab?.id);

      if (!Number.isInteger(createdTabId) || createdTabId <= 0) throw new Error('Created tab identity missing');

      const ready = await waitForCreatedChatWindowReady(createdWindowId, createdTabId);

      return { ok: true, created: true, state: 'PENDING_UNBOUND', ...receiptBase,

        windowId: createdWindowId, tabId: createdTabId,

        windowState: String(ready.win?.state || created?.state || 'normal').toUpperCase(),

        tabPresence: 'OPEN',

        creationReceipt: {

          operationId,

          windowId: createdWindowId,

          tabId: createdTabId,

          url: 'https://chatgpt.com/',

          instanceId: String(state.settings.instanceId || ''),

          sessionId: endpointSessionId,

          conversationKey: '',

          bindingState: 'PENDING_UNBOUND',

          windowState: String(ready.win?.state || created?.state || 'normal').toUpperCase(),

          tabPresence: 'OPEN'

        } };

    } catch (_) {

      return { ok: false, created: true, state: 'CREATE_UNKNOWN', ...receiptBase,

        windowId: Number.isInteger(createdWindowId) ? createdWindowId : null,

        tabId: Number.isInteger(Number(createdTab?.id)) ? Number(createdTab.id) : null,

        windowState: 'UNKNOWN', tabPresence: 'UNKNOWN', error: 'CREATE_UNKNOWN' };

    }

  });

}

async function moveExactChatTab(message) {

  const operationId = String(message.operationId || '').trim();

  const conversationKey = String(message.conversationKey || '').trim();

  const instanceId = String(message.instanceId || '').trim();

  const sessionId = String(message.sessionId || '').trim();

  if (!operationId) throw new Error('Move operation id required');

  const state = await loadState();

  if (!instanceId || instanceId !== String(state.settings.instanceId || '')) throw new Error('Endpoint instance mismatch');

  if (!sessionId || sessionId !== endpointSessionId) throw new Error('Endpoint session mismatch');

  const windowId = await validateExactWindowId(message.windowId);

  const index = Number(message.index);

  if (!Number.isInteger(index) || index < -1) throw new Error('Invalid tab index');

  const fingerprint = JSON.stringify([conversationKey, instanceId, sessionId, Number(message.tabId), windowId, index]);

  return runIdempotentOperation(operationId, 'move-tab', fingerprint, async () => {

    const pending = !conversationKey;

    const resolved = pending

      ? await resolveExactPendingCreatedTab(message)

      : { tab: await resolveExactConversationCommand(message), createOperationId: '' };

    const tab = resolved.tab;

    const sourceWindowId = Number(tab.windowId);

    const windowTabs = await chrome.tabs.query({ windowId });

    const sameWindow = sourceWindowId === windowId;

    if (sameWindow && !windowTabs.some((item) => Number(item.id) === Number(tab.id))) throw new Error('Move source tab missing from window');

    const maxIndex = sameWindow ? Math.max(0, windowTabs.length - 1) : windowTabs.length;

    if (index !== -1 && index > maxIndex) throw new Error('Invalid tab index');

    const moved = await chrome.tabs.move(tab.id, { windowId, index });

    const movedTab = Array.isArray(moved) ? moved.find((item) => Number(item.id) === Number(tab.id)) : moved;

    if (!movedTab || !isChatTab(movedTab) || Number(movedTab.id) !== Number(tab.id)

        || Number(movedTab.windowId) !== windowId

        || RelayCore.conversationKey(movedTab.url || '') !== conversationKey) throw new Error('Move verification failed');

    return { ok: true, operationId, moved: true, tabId: movedTab.id, windowId,

      index: Number(movedTab.index), conversationKey, pendingUnbound: pending,

      createOperationId: resolved.createOperationId };

  });

}

// Promote an already-bound backup only after ACT has proved that the former
// manager endpoint is no longer live. This never sends a chat message.
async function promoteManagerBinding(message) {
  const operationId = String(message.operationId || '').trim();
  if (!operationId) throw new Error('Manager promotion operation id required');
  const managerNode = RelayCore.normalizeRole(message.managerNode || 'MANAGER');
  const backupNode = RelayCore.normalizeRole(message.backupNode || 'BACKUP_MANAGER');
  const instanceId = String(message.instanceId || '').trim();
  const priorManagerReceiptId = String(message.priorManagerReceiptId || '').trim();
  const priorBackupReceiptId = String(message.priorBackupReceiptId || '').trim();
  const newManagerReceiptId = String(message.newManagerReceiptId || '').trim();
  const priorManagerConversationKey = String(message.priorManagerConversationKey || '').trim();
  if (managerNode === backupNode) throw new Error('Manager and backup node must differ');
  if (!instanceId || !priorManagerConversationKey) throw new Error('Manager promotion identity required');
  for (const receipt of [priorManagerReceiptId, priorBackupReceiptId, newManagerReceiptId]) {
    if (!/^RCB-[A-Z0-9]{12,40}$/.test(receipt)) throw new Error('Manager promotion binding receipt required');
  }
  const fingerprint = JSON.stringify([managerNode, backupNode, instanceId, priorManagerConversationKey,
    priorManagerReceiptId, priorBackupReceiptId, newManagerReceiptId,
    String(message.conversationKey || ''), String(message.sessionId || ''), Number(message.tabId)]);
  return runIdempotentOperation(operationId, 'manager-promote', fingerprint, async () => {
    const state = await loadState();
    if (String(state.settings.instanceId || '') !== instanceId) throw new Error('Endpoint instance mismatch');
    const previous = state.registrations?.[managerNode];
    const backup = state.registrations?.[backupNode];
    if (!previous || !backup) throw new Error('MANAGER_PROMOTION_BINDING_REQUIRED');
    if (String(previous.conversationKey || '') !== priorManagerConversationKey
        || String(previous.bindingReceiptId || '') !== priorManagerReceiptId) {
      throw new Error('MANAGER_PROMOTION_MANAGER_FENCE_MISMATCH');
    }
    if (String(backup.bindingReceiptId || '') !== priorBackupReceiptId) {
      throw new Error('MANAGER_PROMOTION_BACKUP_FENCE_MISMATCH');
    }
    const backupTab = await resolveExactConversationCommand({
      conversationKey: String(message.conversationKey || ''),
      sessionId: String(message.sessionId || ''), tabId: Number(message.tabId),
    });
    if (String(backup.conversationKey || '') !== String(message.conversationKey || '')
        || String(backup.sessionId || '') !== String(message.sessionId || '')
        || Number(backup.tabId) !== Number(backupTab.id)) {
      throw new Error('MANAGER_PROMOTION_BACKUP_EXACT_MISMATCH');
    }
    try {
      const oldTab = await chrome.tabs.get(Number(previous.tabId));
      if (isChatTab(oldTab) && RelayCore.conversationKey(oldTab.url || '') === priorManagerConversationKey) {
        throw new Error('MANAGER_ENDPOINT_STILL_LIVE');
      }
    } catch (error) {
      if (String(error?.message || error) === 'MANAGER_ENDPOINT_STILL_LIVE') throw error;
    }
    for (const [role, registration] of Object.entries(state.registrations || {})) {
      if (role !== managerNode && role !== backupNode
          && (String(registration?.conversationKey || '') === String(backup.conversationKey || '')
            || Number(registration?.tabId) === Number(backup.tabId))) {
        throw new Error('CONVERSATION_ALREADY_BOUND');
      }
    }
    const registrations = { ...(state.registrations || {}) };
    delete registrations[managerNode];
    delete registrations[backupNode];
    registrations[managerNode] = {
      ...backup, role: managerNode, bindingReceiptId: newManagerReceiptId,
      authorization: 'ACT_CONVERSATION_BIND', updatedAt: Date.now(),
    };
    await chrome.storage.local.set({ registrations });
    return { ok: true, mutationState: 'APPLIED', managerNode, retiredBackupNode: backupNode,
      priorManagerConversationKey, conversationKey: String(backup.conversationKey || ''),
      sessionId: String(backup.sessionId || ''), tabId: Number(backup.tabId),
      bindingReceiptId: newManagerReceiptId };
  });
}



async function waitForConversationReady(tabId, conversationKey, timeoutMs = 8000) {

  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {

    const tab = await chrome.tabs.get(Number(tabId));

    const url = String(tab?.url || '');

    if (/^https:\/\/(chatgpt\.com|chat\.openai\.com)\//i.test(url) &&

        RelayCore.conversationKey(url) === conversationKey) {

      return tab;

    }

    await new Promise((resolve) => setTimeout(resolve, 50));

  }

  throw new Error(`Conversation did not finish loading: ${conversationKey}`);

}

function postNative(message) {

  try {

    if (nativePort) nativePort.postMessage(message);

  } catch {}

}



let relayNetworkListenersInstalled = false;

function installRelayNetworkListeners() {

  if (relayNetworkListenersInstalled || !chrome.webRequest?.onBeforeRequest) return;

  const relayNetworkFilter = { urls: CHAT_URLS, types: ['xmlhttprequest'] };

  chrome.webRequest.onBeforeRequest.addListener((details) => { correlateRelayNetworkStart(details).catch(() => {}); }, relayNetworkFilter);

  chrome.webRequest.onCompleted.addListener((details) => { correlateRelayNetworkEnd(details, true).catch(() => {}); }, relayNetworkFilter);

  chrome.webRequest.onErrorOccurred.addListener((details) => { correlateRelayNetworkEnd(details, false).catch(() => {}); }, relayNetworkFilter);

  relayNetworkListenersInstalled = true;

}

function scheduleNativeReconnect() {

  if (nativeReconnectTimer) return;

  nativeReconnectTimer = setTimeout(() => {

    nativeReconnectTimer = null;

    connectNativeHost();

  }, 3000);

}



async function getCompletedOperation(operationId, command, fingerprint) {

  const state = await loadState();

  const record = state.operations?.[operationId];

  if (!record) return null;

  if (record.command !== command || record.fingerprint !== fingerprint) throw new Error('OPERATION_ID_REUSE_MISMATCH');

  return record.result || null;

}

async function saveCompletedOperation(operationId, command, fingerprint, result) {

  const state = await loadState();

  const operations = { ...(state.operations || {}) };

  operations[operationId] = { command, fingerprint, result, at: Date.now() };

  const keys = Object.keys(operations).sort((a,b)=>Number(operations[b]?.at||0)-Number(operations[a]?.at||0));

  for (const key of keys.slice(100)) delete operations[key];

  await chrome.storage.local.set({ operations });

}

const nativeOperationInflight = new Map();

async function runIdempotentOperation(operationId, command, fingerprint, work) {

  const completed = await getCompletedOperation(operationId, command, fingerprint);

  if (completed) return { result: completed, replayed: true };

  const running = nativeOperationInflight.get(operationId);

  if (running) {

    if (running.command !== command || running.fingerprint !== fingerprint) throw new Error('OPERATION_ID_REUSE_MISMATCH');

    return { result: await running.promise, replayed: true };

  }

  const promise = (async () => {

    const result = await work();

    await saveCompletedOperation(operationId, command, fingerprint, result);

    return result;

  })();

  nativeOperationInflight.set(operationId, { command, fingerprint, promise });

  try { return { result: await promise, replayed: false }; }

  finally { nativeOperationInflight.delete(operationId); }

}



async function handleNativeCommand(message) {

  await endpointSessionReady;
  if (typeof acceptActNativeResult === 'function' && acceptActNativeResult(message)) return;

  if (message?.type !== 'host:command') return;

  const requestId = String(message.requestId || crypto.randomUUID());

  try {

    if (message.command === 'ping') {

      const state = await loadState();

      postNative({ type: 'host:result', requestId, ok: true, pong: true,

        instanceId: state.settings.instanceId, backgroundBuildId: RCC_BACKGROUND_BUILD_ID });

      return;

    }

    if (message.command === 'state') {

      await endpointSessionReady;

      const state = await loadState();

      const chatTabs = await getChatTabs();

      const tabs = chatTabs.map(publicTab);

      const endpoints = await captureEndpointSnapshot('state', chatTabs);

      postNative({ type: 'host:result', requestId, ok: true, state: {

        instanceId: state.settings.instanceId, sessionId: endpointSessionId, tabs, endpoints,

        registrations: state.registrations, settings: state.settings,

        backgroundBuildId: RCC_BACKGROUND_BUILD_ID

      } });

      return;

    }

    if (message.command === 'result') {

      const relayId = String(message.text || message.relayId || '').trim();

      if (!relayId) throw new Error('RELAY_ID_REQUIRED');

      const state = await loadState();

      const receipt = state.resultReceipts?.[relayId] || null;

      const completed = publicResultFromReceipt(receipt) ||

        (state.results || []).find((item) => String(item?.id || '') === relayId) || null;

      const pending = state.pending?.[relayId] || null;

      postNative({ type: 'host:result', requestId, ok: true, relayId, found: !!completed,

        completed: !!completed, pending: !!pending, result: completed,

        pendingStatus: pending ? { to: String(pending.to || ''), createdAt: Number(pending.createdAt || 0) || null,

          acceptedAt: Number(pending.acceptedAt || 0) || null, submittedAt: Number(pending.submittedAt || 0) || null,

          deliveryConfirmed: pending.deliveryConfirmed === true, deferred: pending.deferred === true,

          networkStartedAt: Number(pending.networkStartedAt || 0) || null,

          networkCompletedAt: Number(pending.networkCompletedAt || 0) || null } : null });

      return;

    }

    if (message.command === 'result-ack') {

      const relayId = String(message.text || message.relayId || '').trim();

      const acknowledged = await acknowledgeDurableResultReceipt(relayId);

      postNative({ type: 'host:result', requestId, ok: true, relayId,

        ackState: String(acknowledged.receipt?.ackState || ''),

        resultHash: String(acknowledged.receipt?.resultHash || ''),

        duplicate: acknowledged.duplicate === true });
      return;

    }

    if (message.command === 'create-chat-tab') {

      const outcome = await createChatTab(message);

      postNative({ type: 'host:result', requestId, ...outcome.result, replayed: outcome.replayed });

      return;

    }

    if (message.command === 'create-chat-window') {

      const outcome = await createChatWindow(message);

      postNative({ type: 'host:result', requestId, ...outcome.result, replayed: outcome.replayed });

      return;

    }

    if (message.command === 'send-to-created-tab') {

      const outcome = await sendToCreatedTab(message);

      postNative({ type: 'host:result', requestId, ...outcome.result, replayed: outcome.replayed });

      return;

    }

    if (message.command === 'move-tab') {

      const outcome = await moveExactChatTab(message);

      postNative({ type: 'host:result', requestId, ...outcome.result, replayed: outcome.replayed });

      return;

    }

    if (message.command === 'manager-promote') {

      const outcome = await promoteManagerBinding(message);

      postNative({ type: 'host:result', requestId, ...outcome.result, replayed: outcome.replayed });

      return;

    }

    if (message.command === 'register') {

      const role = RelayCore.normalizeRole(message.to);

      const key = String(message.text || '').trim();

      const tabs = await getChatTabs();

      const tab = tabs.find((item) => RelayCore.conversationKey(item.url || '') === key);

      if (!tab) throw new Error(`Conversation not open: ${key}`);

      const registration = await registerRole(role, tab.id);

      postNative({ type: 'host:result', requestId, ok: true, registration });

      return;

    }

    if (message.command === 'conversation-bind') {
      const role = RelayCore.normalizeRole(message.to);
      const tab = await resolveExactConversationCommand(message);
      const state = await loadState();
      const current = state.registrations?.[role] || null;
      const conversationKey = String(message.conversationKey || '').trim();
      const promotingBootstrap = !!current

        && current.authorization === 'ACT_CONVERSATION_BOOTSTRAP'

        && !String(current.conversationKey || '')

        && Number(current.tabId) === Number(tab.id)

        && String(current.transportInstanceId || '') === String(state.settings.instanceId || '')

        && String(current.sessionId || '') === String(endpointSessionId || '');

      const changingEndpoint = !!current
        && (String(current.conversationKey || '') !== conversationKey || Number(current.tabId) !== Number(tab.id));
      if (changingEndpoint && !promotingBootstrap) {
        if (message.replaceStale !== true) throw new Error('LOGICAL_NODE_BINDING_CONFLICT');
        if (String(message.expectedCurrentConversationKey || '') !== String(current.conversationKey || '')
          || String(message.expectedCurrentBindingReceiptId || '') !== String(current.bindingReceiptId || '')) {
          throw new Error('LOGICAL_NODE_BINDING_REPLACEMENT_FENCE_MISMATCH');
        }
      }
      for (const [otherRole, registration] of Object.entries(state.registrations || {})) {
        if (otherRole !== role && (String(registration?.conversationKey || '') === conversationKey || Number(registration?.tabId) === Number(tab.id))) throw new Error('CONVERSATION_ALREADY_BOUND');
      }
      const registration = changingEndpoint ? await registerRole(role, tab.id) : (current || await registerRole(role, tab.id));
      if (String(registration?.conversationKey || '') !== conversationKey || Number(registration?.tabId) !== Number(tab.id)) throw new Error('CONVERSATION_BIND_RECEIPT_MISMATCH');
      const bindingReceiptId = String(message.bindingReceiptId || '').trim();
      if (!/^RCB-[A-Z0-9]{12,40}$/.test(bindingReceiptId)) throw new Error('CONVERSATION_BINDING_RECEIPT_REQUIRED');
      registration.transportInstanceId = String(state.settings.instanceId || '');
      registration.sessionId = String(endpointSessionId || '');
      registration.bindingReceiptId = bindingReceiptId;
      registration.authorization = 'ACT_CONVERSATION_BIND';
      registration.updatedAt = Date.now();
      state.registrations[role] = registration;
      await chrome.storage.local.set({ registrations: state.registrations });
      postNative({ type: 'host:result', requestId, ok: true, registration,
        binding: { logicalNode: role, conversationKey, instanceId: state.settings.instanceId,
          sessionId: endpointSessionId, tabId: tab.id, bindingReceiptId } });
      return;
    }

    if (message.command === 'conversation-bootstrap-bind') {

      await endpointSessionReady;

      const role = RelayCore.normalizeRole(message.to);

      const operationId = String(message.operationId || '').trim();

      const bootstrapReceiptId = String(message.bootstrapReceiptId || '').trim();

      if (!operationId) throw new Error('Bootstrap operation id required');

      if (!/^RCI-[A-Z0-9]{12,40}$/.test(bootstrapReceiptId)) throw new Error('CONVERSATION_BOOTSTRAP_RECEIPT_REQUIRED');

      const fingerprint = JSON.stringify([role, String(message.instanceId || ''), String(message.sessionId || ''),

        Number(message.tabId), bootstrapReceiptId]);

      const outcome = await runIdempotentOperation(operationId, 'conversation-bootstrap-bind', fingerprint, async () => {

        const resolved = await resolveExactPendingCreatedTab(message);

        const state = await loadState();

        const current = state.registrations?.[role] || null;

        if (current && (Number(current.tabId) !== Number(resolved.tab.id)

            || String(current.authorization || '') !== 'ACT_CONVERSATION_BOOTSTRAP')) {

          throw new Error('LOGICAL_NODE_BINDING_CONFLICT');

        }

        for (const [otherRole, registration] of Object.entries(state.registrations || {})) {

          if (otherRole !== role && Number(registration?.tabId) === Number(resolved.tab.id)) {

            throw new Error('CONVERSATION_ALREADY_BOUND');

          }

        }

        const registration = {

          role, tabId: Number(resolved.tab.id), conversationKey: '', title: resolved.tab.title || '',

          transportInstanceId: String(state.settings.instanceId || ''), sessionId: endpointSessionId,

          authorization: 'ACT_CONVERSATION_BOOTSTRAP', bootstrapReceiptId, operationId,

          createOperationId: resolved.createOperationId, expiresAt: Date.now() + (10 * 60 * 1000),

          updatedAt: Date.now()

        };

        state.registrations[role] = registration;

        await chrome.storage.local.set({ registrations: state.registrations });

        return { ok: true, registration, bootstrap: true };

      });

      postNative({ type: 'host:result', requestId, ...outcome.result, replayed: outcome.replayed });

      return;

    }

    if (message.command === 'ensure') {

      const registration = await ensureRoleConversation(message.to, message.text);

      postNative({ type: 'host:result', requestId, ok: true, registration });

      return;

    }

    if (message.command === 'recover-pending') {

      const reg = await resolveRegistration(message.to);

      const state = await loadState();

      const relayId = String(message.relayId || message.text || '').trim();

      let pending = state.pending?.[relayId];
      const receipt = state.resultReceipts?.[relayId] || null;

      if (!pending && receipt?.resultState === 'RESULT_PERSISTED') {
        if (Number(receipt.tabId) !== Number(reg.tabId) || receipt.conversationKey !== reg.conversationKey) {
          throw new Error('RELAY_RECOVERY_PENDING_NOT_FOUND');
        }
        pending = {
          relayId,
          to: reg.role,
          tabId: reg.tabId,
          conversationKey: reg.conversationKey,
          createdAt: receipt.createdAt || new Date().toISOString(),
          deliveryConfirmed: true,
          recoveredPending: true,
          returnToRole: String(receipt.returnToRole || ''),
          returnToControl: receipt.returnToControl === true,
          source: 'recovered-durable-result-receipt'
        };
      }

      if (!pending) {

        const inspected = await sendToChatTab(reg.tabId, { type: 'relay:inspectExecution', relayId });

        const record = inspected?.record;

        if (!inspected?.ok || record?.relayId !== relayId || record?.conversationKey !== reg.conversationKey) throw new Error('RELAY_RECOVERY_PENDING_NOT_FOUND');

        pending = {

          relayId,

          to: reg.role,

          tabId: reg.tabId,

          conversationKey: reg.conversationKey,

          createdAt: record.submittedAt || new Date().toISOString(),

          deliveryConfirmed: true,

          recoveredPending: true,

          source: 'recovered-content-record'

        };

        state.pending[relayId] = pending;

        await chrome.storage.local.set({ pending: state.pending });

      }

      if (Number(pending.tabId) !== Number(reg.tabId) || pending.conversationKey !== reg.conversationKey) throw new Error('RELAY_RECOVERY_PENDING_NOT_FOUND');

      if (receipt?.resultState === 'RESULT_PERSISTED') {
        let activeReceipt = receipt;
        if (isRecoverableCaptureResult(receipt.resultPayload)) {
          let submittedText = '';
          try {
            const fingerprintParts = JSON.parse(String(receipt.dispatchFingerprint || ''));
            if (Array.isArray(fingerprintParts) && typeof fingerprintParts[1] === 'string') submittedText = fingerprintParts[1];
          } catch (_) {}
          if (submittedText) {
            const recoveryMessage = {
              type: 'relay:recoverExecution',
              relayId,
              returnOnly: true,
              recoveryRecord: {
                relayId,
                conversationKey: reg.conversationKey,
                submittedText,
                beforeTurnKeys: [],
                routeTurnKey: '',
                phase: 'submitted',
                submittedAt: Number(receipt.createdAt || 0) || Date.now(),
                completionMarker: ''
              }
            };
            let recovered;
            try {
              recovered = await Promise.race([
                sendToChatTab(reg.tabId, recoveryMessage),
                new Promise((_, reject) => setTimeout(() => reject(new Error('RELAY_RECOVERY_CONTENT_RPC_TIMEOUT')), 2000))
              ]);
            } catch (_) {
              recovered = await recoverCompletedReplyDirectlyFromTab(
                reg.tabId, reg.conversationKey, submittedText
              );
            }
            if (recovered?.ok && recovered.recovered === true && String(recovered.recoveredReply || '').trim()) {
              const recoveredReply = String(recovered.recoveredReply || '');
              if (receipt.ackState === 'ACKED' || receipt.returnState === 'DELIVERED') {
                postNative({
                  type: 'host:result',
                  requestId,
                  ok: true,
                  relayId,
                  recovered: true,
                  persistedResult: true,
                  readOnlyRecovery: true,
                  recoveredReply,
                  returnState: String(receipt.returnState || ''),
                  receiverAckState: String(receipt.receiverAckState || '')
                });
                return;
              }
              activeReceipt = await replaceRecoverableResultReceipt(relayId, {
                ok: true,
                reply: recoveredReply,
                recovered: 'route-scoped-final-dom'
              });
            }
          }
        }
        const returned = await returnPersistedResult(relayId, pending, activeReceipt);
        postNative({ type: 'host:result', requestId, ok: true, relayId, recovered: true,
          persistedResult: true, returnState: returned.returnState,
          receiverAckState: returned.receiverAckState, replayed: returned.replayed === true });
        return;
      }

      const reply = await sendToChatTab(reg.tabId, { type: 'relay:recoverExecution', relayId });

      if ((!reply?.ok || reply.recovered !== true) && String(reply?.error || '') === 'RELAY_RECOVERY_RECORD_NOT_FOUND' && pending.deliveryConfirmed !== true) {

        delete state.pending[relayId];

        await chrome.storage.local.set({ pending: state.pending });

        postNative({ type: 'host:result', requestId, ok: true, relayId, recovered: false, discarded: true });

        return;

      }

      if (!reply?.ok || reply.recovered !== true) throw new Error(reply?.error || 'RELAY_RECOVERY_FAILED');

      postNative({ type: 'host:result', requestId, ok: true, relayId, recovered: true });

      return;

    }

    if (message.command === 'clear-relay-state') {

      const reg = await resolveRegistration(message.to);

      const state = await loadState();

      let removedPending = 0;

      for (const [relayId, pending] of Object.entries(state.pending || {})) {

        if (Number(pending?.tabId) === Number(reg.tabId)) { delete state.pending[relayId]; removedPending += 1; }

      }

      await chrome.storage.local.set({ pending: state.pending });

      const injected = await chrome.scripting.executeScript({ target: { tabId: reg.tabId }, func: () => {

        const active = sessionStorage.getItem('relayActiveExecutionV1');

        let queueDepth = 0;

        try { const q = JSON.parse(sessionStorage.getItem('relayDeferredQueueV1') || '[]'); queueDepth = Array.isArray(q) ? q.length : 0; } catch (_) {}

        sessionStorage.removeItem('relayActiveExecutionV1');

        sessionStorage.removeItem('relayDeferredQueueV1');

        return { hadActive: !!active, queueDepth };

      } });

      const cleared = injected?.[0]?.result || {};

      postNative({ type: 'host:result', requestId, ok: true, role: RelayCore.normalizeRole(message.to), removedPending, hadActive: !!cleared.hadActive, queueDepth: Number(cleared.queueDepth || 0) });

      return;

    }

    if (message.command === 'main-capture-install') {

      const reg=await resolveRegistration(message.to);

      const x=await chrome.scripting.executeScript({target:{tabId:reg.tabId},world:'MAIN',func:()=>{

        if (window.__dwRelayCaptureInstalled) return {installed:true,reused:true}; window.__dwRelayCaptureInstalled=true; window.__dwRelayCaptured=[];

        const save=(kind,url,text,error='')=>{ try { window.__dwRelayCaptured.push({kind,url:String(url||''),at:Date.now(),len:String(text||'').length,tail:String(text||'').slice(-12000),error:String(error||'')}); window.__dwRelayCaptured=window.__dwRelayCaptured.slice(-6); } catch(_){} };

        const of=window.fetch; window.fetch=async function(...a){ const r=await of.apply(this,a); try{ const i=a[0],init=a[1]||{},u=typeof i==='string'?i:(i?.url||''),m=String(init.method||i?.method||'GET').toUpperCase(); if(m==='POST'&&String(u).includes('/backend-api/f/conversation')) r.clone().text().then(t=>save('fetch',u,t)).catch(e=>save('fetch',u,'',e)); }catch(_){} return r; };

        const oo=XMLHttpRequest.prototype.open,os=XMLHttpRequest.prototype.send; XMLHttpRequest.prototype.open=function(m,u,...r){this.__dwM=String(m||'GET').toUpperCase();this.__dwU=String(u||'');return oo.call(this,m,u,...r)}; XMLHttpRequest.prototype.send=function(...a){ if(this.__dwM==='POST'&&this.__dwU.includes('/backend-api/f/conversation')) this.addEventListener('loadend',()=>{try{save('xhr',this.__dwU,this.responseType===''||this.responseType==='text'?this.responseText:'')}catch(e){save('xhr',this.__dwU,'',e)}}); return os.apply(this,a); };

        return {installed:true,reused:false};

      }}); postNative({type:'host:result',requestId,ok:true,result:x?.[0]?.result||null}); return;

    }

    if (message.command === 'main-capture-get') {

      const reg=await resolveRegistration(message.to); const x=await chrome.scripting.executeScript({target:{tabId:reg.tabId},world:'MAIN',func:()=>window.__dwRelayCaptured||[]}); postNative({type:'host:result',requestId,ok:true,captured:x?.[0]?.result||[]}); return;

    }

    if (message.command === 'api-probe') {

      const reg = await resolveRegistration(message.to);

      const key = String(reg.conversationKey || '');

      const injected = await chrome.scripting.executeScript({ target: { tabId: reg.tabId }, func: async (conversationKey) => {

        const urls=[`/backend-api/conversation/${conversationKey}`,`/backend-api/conversations/${conversationKey}`]; const out=[];

        for (const url of urls) { try { const r=await fetch(url,{credentials:'include',cache:'no-store'}); const text=await r.text(); out.push({url,status:r.status,ok:r.ok,preview:text.slice(0,800)}); } catch (e) { out.push({url,error:String(e?.message||e)}); } }

        return out;

      }, args: [key] });

      postNative({ type:'host:result', requestId, ok:true, role:RelayCore.normalizeRole(message.to), api:injected?.[0]?.result || [] });

      return;

    }

    if (message.command === 'probe-tabs') {
      const tabs = (await getChatTabs()).filter(isChatTab);
      const probes = [];
      for (const tab of tabs) {
        let probe = null;
        let error = '';
        try {
          probe = await chrome.tabs.sendMessage(tab.id, { type: 'relay:probe' });
        } catch (err) {
          error = String(err?.message || err);
        }
        probes.push({
          tabId: tab.id,
          windowId: tab.windowId,
          conversationKey: RelayCore.conversationKey(tab.url || ''),
          title: tab.title || '',
          ok: probe?.ok === true,
          buildVersion: String(probe?.buildVersion || ''),
          contentVersion: String(probe?.contentVersion || ''),
          error
        });
      }
      postNative({ type: 'host:result', requestId, ok: true, probes });
      return;
    }

    if (message.command === 'diagnose-activity') {

      const key = String(message.text || '').trim();

      const tabs = (await getChatTabs()).filter((tab) => !key || RelayCore.conversationKey(tab?.url || '') === key);

      const diagnostics = [];

      for (const tab of tabs) {

        try {

          const result = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => {

            const items = [...document.querySelectorAll('button,[data-testid],[aria-label]')].map((el) => ({

              tag: el.tagName, testid: el.getAttribute('data-testid') || '', aria: el.getAttribute('aria-label') || '',

              title: el.getAttribute('title') || '', text: String(el.textContent || '').trim().slice(0,80), disabled: !!el.disabled

            }));

            return items.filter((x) => /stop|cancel|send|submit|voice|record|generat|중지|전송|음성|보내/i.test([x.testid,x.aria,x.title,x.text].join(' '))).slice(0,80);

          }});

          diagnostics.push({ tabId: tab.id, conversationKey: RelayCore.conversationKey(tab.url || ''), title: tab.title || '', items: result?.[0]?.result || [] });

        } catch (error) { diagnostics.push({ tabId: tab.id, error: String(error?.message || error) }); }

      }

      postNative({ type: 'host:result', requestId, ok: true, diagnostics });

      return;

    }

    if (message.command === 'diagnose-conversation-ui') {
      const key = String(message.conversationKey || message.text || '').trim();
      const tabs = (await getChatTabs()).filter((tab) => !key || RelayCore.conversationKey(tab?.url || '') === key);
      const diagnostics = [];
      for (const tab of tabs) {
        try {
          const result = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: () => {
              const visible = (el) => {
                if (!el || el.getClientRects().length === 0) return false;
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) return false;
                const style = getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) !== 0;
              };
              const pack = (el) => {
                const rect = el.getBoundingClientRect();
                return {
                  tag: el.tagName,
                  role: el.getAttribute('role') || '',
                  href: el.getAttribute('href') || '',
                  testid: el.getAttribute('data-testid') || '',
                  sidebar: el.getAttribute('data-sidebar-item') || '',
                  aria: el.getAttribute('aria-label') || '',
                  title: el.getAttribute('title') || '',
                  text: String(el.textContent || '').replace(/\s+/g,' ').trim().slice(0,120),
                  left: Math.round(rect.left), top: Math.round(rect.top),
                  width: Math.round(rect.width), height: Math.round(rect.height)
                };
              };
              const rowSelector = '[data-sidebar-item="true"], nav li, aside li';
              const rows = Array.from(document.querySelectorAll(rowSelector)).filter(visible).map(pack).slice(0,120);
              const links = Array.from(document.querySelectorAll('a[href]')).filter((el) => {
                if (!visible(el)) return false;
                const href = String(el.getAttribute('href') || '');
                return /\/c\/[a-z0-9-]{8,64}/i.test(href);
              }).map(pack).slice(0,120);
              const buttons = Array.from(document.querySelectorAll('button')).filter((el) => {
                if (!visible(el) || el.disabled) return false;
                const text = [el.getAttribute('aria-label'),el.getAttribute('title'),el.getAttribute('data-testid'),el.textContent].filter(Boolean).join(' ');
                return /sidebar|side bar|menu|more|options|chat|conversation|history|사이드|메뉴|옵션|더 보기|대화|채팅/i.test(text);
              }).map(pack).slice(0,120);
              const assistantSelector = [
                '[data-message-author-role="assistant"]',
                '[data-content-search-unit-key$=":assistant"]',
                '[data-chatgpt-search-unit-key$=":assistant"]',
                '[data-markdown-text-style="assistant-message"]'
              ].join(',');
              const userSelector = [
                '[data-message-author-role="user"]',
                '[data-content-search-unit-key$=":user"]',
                '[data-user-message-bubble="true"]'
              ].join(',');
              const userNodes = Array.from(document.querySelectorAll(userSelector));
              const userUnits = userNodes.map((el, index) => {
                const closestTurn = el.closest('[data-turn-key],[data-content-search-turn-key],[data-testid^="conversation-turn-"]');
                const clone = el.cloneNode(true);
                clone.querySelectorAll('button,[role="button"],[contenteditable="true"]').forEach((item) => item.remove());
                return {
                  index,
                  visible: visible(el),
                  turnKey: closestTurn?.getAttribute('data-turn-key') || closestTurn?.getAttribute('data-content-search-turn-key') || closestTurn?.getAttribute('data-testid') || '',
                  textLength: String(clone.textContent || '').trim().length,
                  textPreview: String(clone.textContent || '').replace(/\s+/g,' ').trim().slice(0,260),
                  textFull: String(clone.textContent || '').trim()
                };
              }).slice(-40);
              const assistantNodes = Array.from(document.querySelectorAll(assistantSelector));
              const assistantUnits = assistantNodes.map((el, index) => {
                const closestTurn = el.closest('[data-turn-key],[data-content-search-turn-key],[data-testid^="conversation-turn-"]');
                return {
                  index,
                  visible: visible(el),
                  tag: el.tagName,
                  authorRole: el.getAttribute('data-message-author-role') || '',
                  unitKey: el.getAttribute('data-content-search-unit-key') || el.getAttribute('data-chatgpt-search-unit-key') || '',
                  markdownStyle: el.getAttribute('data-markdown-text-style') || '',
                  turnKey: closestTurn?.getAttribute('data-turn-key') || closestTurn?.getAttribute('data-content-search-turn-key') || closestTurn?.getAttribute('data-testid') || '',
                  nestedAssistantCount: el.querySelectorAll(assistantSelector).length,
                  textLength: String(el.innerText || el.textContent || '').trim().length,
                  textPreview: String(el.innerText || el.textContent || '').replace(/\s+/g,' ').trim().slice(0,160)
                };
              }).slice(-40);
              let relayExecution = null;
              try {
                const raw = sessionStorage.getItem('relayActiveExecutionV1');
                const parsed = raw ? JSON.parse(raw) : null;
                if (parsed && typeof parsed === 'object') {
                  relayExecution = {
                    relayId: String(parsed.relayId || ''),
                    conversationKey: String(parsed.conversationKey || ''),
                    routeTurnKey: String(parsed.routeTurnKey || ''),
                    phase: String(parsed.phase || ''),
                    submittedAt: parsed.submittedAt || null,
                    beforeTurnKeys: Array.isArray(parsed.beforeTurnKeys) ? parsed.beforeTurnKeys.slice(-8) : []
                  };
                }
              } catch (_) {}
              return { href: location.href, documentTitle: document.title, rows, links, buttons, userUnits, assistantUnits, relayExecution };
            }
          });
          diagnostics.push({
            tabId: tab.id,
            conversationKey: RelayCore.conversationKey(tab.url || ''),
            title: tab.title || '',
            ui: result?.[0]?.result || null
          });
        } catch (error) {
          diagnostics.push({ tabId: tab.id, error: String(error?.message || error) });
        }
      }
      let recoveryProbe = null;
      const probeRelayId = String(message.relayId || '').trim();
      const probeRole = String(message.to || '').trim();
      if (probeRelayId && probeRole) {
        try {
          const data = await chrome.storage.local.get([RELAY_RESULT_RECEIPTS_KEY]);
          const probeReceipt = (data[RELAY_RESULT_RECEIPTS_KEY] || {})[probeRelayId] || null;
          const probeReg = await resolveRegistration(probeRole);
          let submittedText = '';
          try {
            const parts = JSON.parse(String(probeReceipt?.dispatchFingerprint || ''));
            if (Array.isArray(parts) && typeof parts[1] === 'string') submittedText = parts[1];
          } catch (_) {}
          const recovered = await recoverCompletedReplyDirectlyFromTab(
            probeReg.tabId, probeReg.conversationKey, submittedText
          );
          recoveryProbe = {
            ok: recovered?.ok === true,
            replyLength: String(recovered?.recoveredReply || '').length,
            replyPreview: String(recovered?.recoveredReply || '').slice(0, 220)
          };
        } catch (error) {
          let comparison = null;
          try {
            const compare = await chrome.scripting.executeScript({
              target: { tabId: probeReg.tabId },
              args: [submittedText],
              func: (submittedRaw) => {
                const norm = (value) => String(value || '').replace(/\u00a0/g,' ').replace(/\s+/g,' ').trim();
                const submitted = norm(submittedRaw);
                const turns = Array.from(document.querySelectorAll(
                  '[data-turn-key],[data-content-search-turn-key],[data-testid^="conversation-turn-"]'
                ));
                const seen = new Set();
                const rows = [];
                for (const node of turns) {
                  const turn = node.matches('[data-turn-key]') ? node : (node.closest('[data-turn-key]') || node);
                  if (seen.has(turn)) continue;
                  seen.add(turn);
                  const user = turn.querySelector(
                    '[data-message-author-role="user"],[data-content-search-unit-key$=":user"],[data-user-message-bubble="true"]'
                  );
                  if (!user) continue;
                  const clone = user.cloneNode(true);
                  clone.querySelectorAll('button,[role="button"],[contenteditable="true"]').forEach((item) => item.remove());
                  const rendered = norm(clone.textContent || '');
                  let diff = -1;
                  const min = Math.min(submitted.length, rendered.length);
                  for (let i = 0; i < min; i += 1) {
                    if (submitted[i] !== rendered[i]) { diff = i; break; }
                  }
                  if (diff < 0 && submitted.length !== rendered.length) diff = min;
                  rows.push({
                    turnKey: turn.getAttribute('data-turn-key') || turn.getAttribute('data-content-search-turn-key') || turn.getAttribute('data-testid') || '',
                    submittedLength: submitted.length,
                    renderedLength: rendered.length,
                    diff,
                    submittedChar: diff >= 0 ? submitted.charCodeAt(diff) : null,
                    renderedChar: diff >= 0 ? rendered.charCodeAt(diff) : null,
                    submittedAround: diff >= 0 ? submitted.slice(Math.max(0,diff-20),diff+21) : '',
                    renderedAround: diff >= 0 ? rendered.slice(Math.max(0,diff-20),diff+21) : ''
                  });
                }
                return rows;
              }
            });
            comparison = compare?.[0]?.result || null;
          } catch (_) {}
          recoveryProbe = { ok: false, error: String(error?.message || error || ''), comparison };
        }
      }
      postNative({ type: 'host:result', requestId, ok: true, diagnostics, recoveryProbe });
      return;
    }

    if (message.command === 'diagnose-composer') {
      const tabs = (await getChatTabs()).filter(isChatTab);
      const diagnostics = [];
      for (const tab of tabs) {
        try {
          const result = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: () => {
              const selectors = [
                '#prompt-textarea',
                'div[contenteditable="true"][role="textbox"]',
                'div[contenteditable="true"][data-virtualkeyboard="true"]',
                'textarea[name="prompt-textarea"]'
              ];
              let editor = null;
              for (const selector of selectors) {
                editor = document.querySelector(selector);
                if (editor) break;
              }
              const form = editor?.closest?.('form') || null;
              const buttons = Array.from((form || document).querySelectorAll('button')).map((button) => ({
                type: button.getAttribute('type') || '',
                testid: button.getAttribute('data-testid') || '',
                aria: button.getAttribute('aria-label') || '',
                title: button.getAttribute('title') || '',
                text: String(button.textContent || '').trim().slice(0, 80),
                disabled: !!button.disabled,
                visible: button.getClientRects().length > 0
              })).slice(0, 80);
              return {
                href: location.href,
                editor: editor ? {
                  tag: editor.tagName,
                  value: typeof editor.value === 'string' ? editor.value : '',
                  text: String(editor.innerText || editor.textContent || ''),
                  html: String(editor.innerHTML || '').slice(0, 1500),
                  contenteditable: editor.getAttribute('contenteditable') || '',
                  role: editor.getAttribute('role') || '',
                  testid: editor.getAttribute('data-testid') || '',
                  aria: editor.getAttribute('aria-label') || '',
                  placeholder: editor.getAttribute('placeholder') || editor.getAttribute('data-placeholder') || ''
                } : null,
                form: form ? {
                  method: form.getAttribute('method') || '',
                  action: form.getAttribute('action') || '',
                  text: String(form.textContent || '').trim().slice(0, 300)
                } : null,
                buttons
              };
            }
          });
          diagnostics.push({ tabId: tab.id, title: tab.title || '', url: tab.url || '', result: result?.[0]?.result || null });
        } catch (error) {
          diagnostics.push({ tabId: tab.id, title: tab.title || '', url: tab.url || '', error: String(error?.message || error) });
        }
      }
      postNative({ type: 'host:result', requestId, ok: true, diagnostics });
      return;
    }

    if (message.command === 'probe') {

      const reg = await resolveRegistration(message.to);

      const probe = await sendToChatTab(reg.tabId, { type: 'relay:probe' });

      const state = await loadState();

      const pending = Object.entries(state.pending || {}).filter(([, item]) => Number(item?.tabId) === Number(reg.tabId)).map(([relayId, item]) => ({

        relayId, deliveryConfirmed: item?.deliveryConfirmed === true,

        networkPath: String(item?.networkPath || ''), networkRequestId: String(item?.networkRequestId || ''),

        networkStartedAt: Number(item?.networkStartedAt || 0) || null,

        networkCompletedAt: Number(item?.networkCompletedAt || 0) || null,

        networkOk: item?.networkOk !== false, networkCandidates: Array.isArray(item?.networkCandidates) ? item.networkCandidates : [], createdAt: Number(item?.createdAt || 0) || null

      }));

      postNative({ type: 'host:result', requestId, ok: true, role: RelayCore.normalizeRole(message.to), probe, pending });

      return;

    }

    if (message.command === 'close-conversation-tab') {

      const operationId = String(message.operationId || '').trim();

      const conversationKey = String(message.conversationKey || '').trim();

      if (!operationId) throw new Error('Close operation id required');

      const fingerprint = JSON.stringify([conversationKey, Number(message.tabId), String(message.sessionId || '')]);

      const outcome = await runIdempotentOperation(operationId, 'close-conversation-tab', fingerprint, async () => {

        const tab = await resolveExactConversationCommand(message);

        const result = { ok: true, operationId, closed: true, tabId: tab.id, conversationKey };

        await chrome.tabs.remove(tab.id);

        return result;

      });

      postNative({ type: 'host:result', requestId, ...outcome.result, replayed: outcome.replayed });

      return;

    }

    if (message.command === 'rename-conversation') {

      const title = String(message.title || '').trim();

      const operationId = String(message.operationId || '').trim();

      const conversationKey = String(message.conversationKey || '');

      if (!title || title.length > 100) throw new Error('Invalid conversation title');

      if (!operationId) throw new Error('Rename operation id required');

      const fingerprint = JSON.stringify([conversationKey, Number(message.tabId), String(message.sessionId || ''), title]);

      const outcome = await runIdempotentOperation(operationId, 'rename-conversation', fingerprint, async () => {

        const tab = await resolveExactConversationCommand(message);

        const reply = await sendToChatTab(tab.id, { type: 'relay:renameConversation', conversationKey, title, operationId });

        if (!reply?.ok || String(reply.savedTitle || '').trim() !== title) throw new Error(reply?.error || 'Conversation rename not confirmed');

        const current = await resolveExactConversationCommand(message);

        await publishEndpointSnapshot('conversation-renamed');

        return { ok: true, operationId, savedTitle: title, tabId: current.id, conversationKey };

      });

      postNative({ type: 'host:result', requestId, ...outcome.result, replayed: outcome.replayed });

      return;

    }

    if (message.command === 'reload-extension') {

      postNative({ type: 'host:result', requestId, ok: true, reloading: true });

      setTimeout(() => chrome.runtime.reload(), 50);

      return;

    }

    if (message.command === 'reload-workers') {

      const state = await loadState();

      const requestedRole = String(message.to || '').trim() ? RelayCore.normalizeRole(message.to) : '';

      const reloaded = [];

      const skipped = [];

      for (const [role, reg] of Object.entries(state.registrations || {})) {

        if (requestedRole && role !== requestedRole) continue;

        if (role === CONTROL || role === 'TEST') { skipped.push({ role, reason: 'protected' }); continue; }

        const tabId = Number(reg?.tabId);

        if (!Number.isInteger(tabId)) { skipped.push({ role, reason: 'no-tab' }); continue; }

        try {

          const tab = await chrome.tabs.get(tabId);

          const key = RelayCore.conversationKey(tab?.url || '');

          if (!isChatTab(tab) || (reg.conversationKey && key !== reg.conversationKey)) {

            skipped.push({ role, reason: 'identity-mismatch' });

            continue;

          }

          await chrome.tabs.reload(tabId);

          reloaded.push({ role, tabId, conversationKey: key });

        } catch (error) {

          skipped.push({ role, reason: String(error?.message || error) });

        }

      }

      postNative({ type: 'host:result', requestId, ok: true, reloaded, skipped });

      return;

    }

    if (message.command === 'probe') {

      const reg = await resolveRegistration(message.to);

      const probe = await sendToChatTab(reg.tabId, { type: 'relay:probe' });

      postNative({ type: 'host:result', requestId, ok: true, role: message.to, probe });

      return;

    }

    if (message.command !== 'send' && message.command !== 'send-wakeback') throw new Error(`Unknown native command: ${message.command}`);

    const result = await dispatchRelay({ to: message.to, text: message.text, id: requestId,

      source: 'native', fromNode: message.fromNode, messageHash: message.messageHash,

      targetBindingReceipt: message.bindingReceiptId, returnToControl: false,

      returnToRole: message.command === 'send-wakeback' ? 'WORKER' : String(message.returnTo || '').trim(), hostRequestId: requestId });

    if (result.completed && result.completedResult) {

      const done = result.completedResult;

      postNative({ type: 'host:result', requestId, relayId: result.relayId, from: done.from || result.to,

        ok: !!done.ok, reply: String(done.reply || ''), error: String(done.error || ''), replayed: true });

    } else if (result.pending && result.deliveryConfirmed !== true) {

      postNative({ type: 'host:result', requestId, relayId: result.relayId, ok: false, ambiguous: true, error: 'RELAY_DELIVERY_UNCONFIRMED' });

    } else {

      postNative({ type: 'host:ack', requestId, relayId: result.relayId, ok: true, submitted: result.deferred === true ? false : true, deferred: result.deferred === true, replayed: !!result.duplicate });

    }

  } catch (error) {

    postNative({ type: 'host:result', requestId, ok: false, error: error.message });

  }

}



async function ensureActivityBridges(tabsValue = null) {

  await forEachChatTabBounded(tabsValue, async (tab) => {

    try {

      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['activity_bridge.js'] });

    } catch (_) {}

  });

}



async function ensureNaturalRoleBridges(tabsValue = null) {

  await forEachChatTabBounded(tabsValue, async (tab) => {

    try {

      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['act_command_bridge.js'] });

    } catch (_) {}

  });

}



async function notifyRelayLocalState(tabsValue = null) {

  await forEachChatTabBounded(tabsValue, async (tab) => {

    try { await sendToChatTab(tab.id, { type: 'relay:refreshLocalState' }); } catch (_) {}

  });

}



async function reconcileRegistrationsWithTabs(tabsValue = null) {

  await endpointSessionReady;

  const state = await loadState();

  const tabs = (Array.isArray(tabsValue) ? tabsValue : await getChatTabs()).filter(isChatTab);

  let changed = false;

  for (const reg of Object.values(state.registrations || {})) {

    if (!reg?.conversationKey) continue;

    const match = tabs.find((tab) => RelayCore.conversationKey(tab.url || '') === reg.conversationKey);

    if (!match) continue;

    // A Chrome extension reload rotates the ephemeral endpoint session while
    // preserving the extension instance, the durable binding receipt, and the
    // live conversation URL. Reconnect only that same exact binding.
    const reconnectableDynamicBinding = reg.authorization === 'ACT_CONVERSATION_BIND'
      && /^RCB-[A-Z0-9]{12,40}$/.test(String(reg.bindingReceiptId || ''))
      && String(reg.transportInstanceId || '') === String(state.settings.instanceId || '');
    const needsTabRefresh = Number(reg.tabId) !== Number(match.id);
    const needsSessionRefresh = reconnectableDynamicBinding
      && String(reg.sessionId || '') !== String(endpointSessionId || '');
    if (needsTabRefresh || needsSessionRefresh) {
      reg.tabId = match.id;
      reg.title = match.title || reg.title;
      if (needsSessionRefresh) reg.sessionId = String(endpointSessionId || '');
      reg.updatedAt = Date.now();
      changed = true;
    }

  }

  if (changed) await chrome.storage.local.set({ registrations: state.registrations });

  return state.registrations;

}



async function reconcilePendingRelayTargets(reason = 'reconcile', tabsValue = null) {

  const state = await loadState();

  const tabs = (Array.isArray(tabsValue) ? tabsValue : await getChatTabs()).filter(isChatTab);

  const byId = new Map(tabs.map((tab) => [Number(tab.id), tab]));

  let changed = false;

  for (const [relayId, pending] of Object.entries(state.pending || {})) {

    const tab = byId.get(Number(pending?.tabId));

    const expectedKey = String(pending?.conversationKey || '');

    const currentKey = tab ? RelayCore.conversationKey(tab.url || '') : '';

    if (tab && (!expectedKey || currentKey === expectedKey)) continue;

    const error = 'RELAY_RESULT_AMBIGUOUS_TARGET_GONE';

    const durable = await persistDurableResultReceipt(relayId, pending, {

      ok: false, reply: '', error, ambiguous: true

    });

    const latest = await loadState();

    if (latest.pending?.[relayId]) delete latest.pending[relayId];

    latest.results.unshift({

      id: relayId, from: String(pending?.to || ''), ok: false, reply: '', error,

      fingerprint: String(pending?.fingerprint || ''), ambiguous: true, reason,

      at: Date.now()

    });

    latest.results = latest.results.slice(0, 50);

    await chrome.storage.local.set({ pending: latest.pending, results: latest.results });

    if (pending?.hostRequestId) {

      postNative({ type: 'host:result', requestId: String(pending.hostRequestId), relayId,

        from: String(pending?.to || ''), ok: false, error, ambiguous: true });

    }

    changed = changed || !durable.duplicate;

  }

  const finalState = await loadState();

  return { changed, pendingCount: Object.keys(finalState.pending || {}).length };

}



async function forceRelayRefresh(reason = 'manual-refresh') {

  const tabs = (await getChatTabs()).filter(isChatTab);

  await ensureActivityBridges(tabs);

  await ensureNaturalRoleBridges(tabs);

  const registrations = await reconcileRegistrationsWithTabs(tabs);

  const pending = await reconcilePendingRelayTargets(reason, tabs);

  await notifyRelayLocalState(tabs);

  const endpoints = await publishEndpointSnapshot(reason, tabs);

  return { ok: true, endpointCount: endpoints.length, registrationCount: Object.keys(registrations || {}).length,

    pendingCount: pending.pendingCount, pendingChanged: pending.changed };

}



async function connectNativeHost() {

  if (nativePort) return;

  try {

    const port = chrome.runtime.connectNative(NATIVE_HOST);

    nativePort = port;

    port.onMessage.addListener((message) => handleNativeCommand(message));

    port.onDisconnect.addListener(() => { nativePort = null; scheduleNativeReconnect(); });

    const state = await loadState();

    postNative({ type: 'host:ready', extensionId: chrome.runtime.id,

      instanceId: state.settings.instanceId });

    (async () => {

      const tabs = (await getChatTabs()).filter(isChatTab);

      await ensureRelayReceivers(tabs);

      await ensureActivityBridges(tabs);

      await ensureNaturalRoleBridges(tabs);

      await reconcileRegistrationsWithTabs(tabs);

      await reconcilePendingRelayTargets('native-connect', tabs);

      await publishEndpointSnapshot('native-connect', tabs);

    })().catch(() => {});

  } catch {

    nativePort = null;

    scheduleNativeReconnect();

  }

}



async function registerRole(roleValue, tabId) {

  const role = RelayCore.normalizeRole(roleValue);

  const tab = await chrome.tabs.get(Number(tabId));

  if (!tab.url || !/^https:\/\/(chatgpt\.com|chat\.openai\.com)\//i.test(tab.url)) {

    throw new Error('Only ChatGPT tabs can be registered');

  }

  const state = await loadState();

  for (const [name, item] of Object.entries(state.registrations)) {

    if (name !== role && item.tabId === tab.id) delete state.registrations[name];

  }

  state.registrations[role] = {

    role,

    tabId: tab.id,

    conversationKey: RelayCore.conversationKey(tab.url),

    title: tab.title || '',

    updatedAt: Date.now()

  };

  await chrome.storage.local.set({ registrations: state.registrations });

  await notifyRelayLocalState();

  return state.registrations[role];

}



async function ensureRoleConversation(roleValue, conversationKeyValue) {

  const role = RelayCore.normalizeRole(roleValue);

  const key = String(conversationKeyValue || '').trim();

  if (!/^[a-z0-9-]{8,64}$/i.test(key)) {

    throw new Error(`Invalid conversation key: ${key}`);

  }

  const tabs = await getChatTabs();

  let tab = tabs.find((item) => RelayCore.conversationKey(item.url || '') === key);

  if (!tab) {

    const created = await chrome.tabs.create({ url: `https://chatgpt.com/c/${key}`, active: false });

    tab = await waitForConversationReady(created.id, key);

  }

  return registerRole(role, tab.id);

}



async function resolveRegistration(roleValue) {

  const role = RelayCore.normalizeRole(roleValue);

  const state = await loadState();

  const reg = state.registrations[role];

  if (!reg) throw new Error(`Role not registered: ${role}`);

  if (reg.tabId) {

    try {

      const tab = await chrome.tabs.get(reg.tabId);

      if (tab.url && /^https:\/\/(chatgpt\.com|chat\.openai\.com)\//i.test(tab.url)) {

        const currentKey = RelayCore.conversationKey(tab.url);

        if (reg.conversationKey && currentKey && currentKey !== reg.conversationKey) {

          throw new Error(`Registered conversation changed for ${role}`);

        }

        return reg;

      }

    } catch {}

  }

  const tabs = await getChatTabs();

  const match = tabs.find((tab) => RelayCore.conversationKey(tab.url || '') === reg.conversationKey);

  if (!match) throw new Error(`Registered tab is not open: ${role}`);

  reg.tabId = match.id;

  reg.title = match.title || reg.title;

  reg.updatedAt = Date.now();

  state.registrations[role] = reg;

  await chrome.storage.local.set({ registrations: state.registrations });

  return reg;

}

function registrationHasDynamicAuthorization(registration, state) {
  return !!registration
    && registration.authorization === 'ACT_CONVERSATION_BIND'
    && /^RCB-[A-Z0-9]{12,40}$/.test(String(registration.bindingReceiptId || ''))
    && String(registration.transportInstanceId || '') === String(state?.settings?.instanceId || '')
    && String(registration.sessionId || '') === String(endpointSessionId || '');
}

function registrationHasBootstrapAuthorization(registration, state) {

  return !!registration

    && registration.authorization === 'ACT_CONVERSATION_BOOTSTRAP'

    && /^RCI-[A-Z0-9]{12,40}$/.test(String(registration.bootstrapReceiptId || ''))

    && !String(registration.conversationKey || '')

    && Number(registration.expiresAt || 0) > Date.now()

    && String(registration.transportInstanceId || '') === String(state?.settings?.instanceId || '')

    && String(registration.sessionId || '') === String(endpointSessionId || '');

}

async function authorizeInjectionSender(sender, requestedConversationKey) {
  await endpointSessionReady;
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !isChatTab(sender.tab)) {
    return { ok: true, authorized: false, reason: 'RCC_UNTRUSTED_INJECTION_SENDER' };
  }
  const tabId = Number(sender.tab?.id);
  const liveKey = RelayCore.conversationKey(sender.tab?.url || '');
  const requestedKey = String(requestedConversationKey || '').trim();
  if (liveKey && requestedKey !== liveKey) {
    return { ok: true, authorized: false, reason: 'RCC_INJECTION_CONVERSATION_MISMATCH' };
  }
  const state = await loadState();

  if (!liveKey && !requestedKey) {

    const pendingBootstrapSends = Object.entries(state.pending || {}).filter(([, pending]) =>

      pending?.bootstrapCreatedTab === true

      && Number(pending?.tabId) === tabId

      && String(pending?.instanceId || '') === String(state.settings?.instanceId || '')

      && String(pending?.sessionId || '') === String(endpointSessionId || '')

      && ['INTENT_RECORDED', 'SUBMITTED'].includes(String(pending?.submissionState || '')));

    if (pendingBootstrapSends.length === 1) {

      return { ok: true, authorized: true, logicalNode: '', conversationKey: '',

        instanceId: String(state.settings?.instanceId || ''), sessionId: endpointSessionId, tabId,

        bootstrapCreatedTab: true, operationId: pendingBootstrapSends[0][0] };

    }

    if (pendingBootstrapSends.length > 1) {

      return { ok: true, authorized: false, reason: 'RCC_INJECTION_BOOTSTRAP_AMBIGUOUS' };

    }

    const bootstrapMatches = Object.values(state.registrations || {}).filter((registration) =>

      Number(registration?.tabId) === tabId && registrationHasBootstrapAuthorization(registration, state));

    if (bootstrapMatches.length !== 1) {

      return { ok: true, authorized: false, reason: bootstrapMatches.length ? 'RCC_INJECTION_BINDING_AMBIGUOUS' : 'RCC_INJECTION_BINDING_REQUIRED' };

    }

    return { ok: true, authorized: true, logicalNode: bootstrapMatches[0].role,

      conversationKey: '', instanceId: bootstrapMatches[0].transportInstanceId,

      sessionId: bootstrapMatches[0].sessionId, tabId };

  }
  const matches = Object.values(state.registrations || {}).filter((registration) =>
    Number(registration?.tabId) === tabId
    && String(registration?.conversationKey || '') === liveKey
    && registrationHasDynamicAuthorization(registration, state));
  if (matches.length !== 1) {
    return { ok: true, authorized: false, reason: matches.length ? 'RCC_INJECTION_BINDING_AMBIGUOUS' : 'RCC_INJECTION_BINDING_REQUIRED' };
  }
  const registration = matches[0];
  return { ok: true, authorized: true, logicalNode: registration.role,
    conversationKey: liveKey, instanceId: registration.transportInstanceId,
    sessionId: registration.sessionId, tabId, bindingReceiptId: registration.bindingReceiptId };
}



const nativeRelayInflight = new Map();

async function dispatchRelay({ to, text, id, source, fromNode = '', messageHash = '',

  targetBindingReceipt = '', returnToControl, returnToRole = '', hostRequestId }) {

  const role = RelayCore.normalizeRole(to);

  if (role === CONTROL) throw new Error('CONTROL cannot be a worker target');

  const relayId = id || crypto.randomUUID();

  const payloadText = String(text || '').slice(0, 12000);

  const fingerprint = JSON.stringify([role, payloadText, !!returnToControl, String(returnToRole || '')]);

  const running = nativeRelayInflight.get(relayId);

  if (running) {

    if (running.fingerprint !== fingerprint) throw new Error('RELAY_ID_REUSE_MISMATCH');

    return { ...(await running.promise), duplicate: true, inflight: true };

  }

  const promise = dispatchRelayOnce({ role, payloadText, relayId, source, fromNode,

    messageHash, targetBindingReceipt, returnToControl, returnToRole, hostRequestId, fingerprint });

  nativeRelayInflight.set(relayId, { fingerprint, promise });

  try { return await promise; }

  finally { nativeRelayInflight.delete(relayId); }

}

async function dispatchRelayOnce({ role, payloadText, relayId, source, fromNode = '',

  messageHash = '', targetBindingReceipt = '', returnToControl, returnToRole = '', hostRequestId, fingerprint }) {

  const reg = await resolveRegistration(role);

  const state = await loadState();

  const bootstrapAuthorized = registrationHasBootstrapAuthorization(reg, state);

  if (!registrationHasDynamicAuthorization(reg, state) && !bootstrapAuthorized) throw new Error('CHAT_INJECTION_DISABLED');

  const completed = publicResultFromReceipt(state.resultReceipts?.[relayId]) ||

    (state.results || []).find((item) => String(item?.id || '') === relayId);

  if (completed) {

    if (String(completed.fingerprint || '') && completed.fingerprint !== fingerprint) throw new Error('RELAY_ID_REUSE_MISMATCH');

    return { ok: true, relayId, to: completed.from || role, duplicate: true, completed: true, completedResult: completed };

  }

  const existing = state.pending?.[relayId];

  if (existing) {

    if (existing.fingerprint && existing.fingerprint !== fingerprint) throw new Error('RELAY_ID_REUSE_MISMATCH');

    if (existing.to !== role) throw new Error('RELAY_ID_REUSE_MISMATCH');

    return { ok: true, relayId, to: role, duplicate: true, pending: true, deliveryConfirmed: existing.deliveryConfirmed === true };

  }

  if (bootstrapAuthorized && reg.bootstrapConsumedAt) throw new Error('CONVERSATION_BOOTSTRAP_ALREADY_CONSUMED');

  state.pending[relayId] = { to: role, tabId: reg.tabId, conversationKey: String(reg.conversationKey || ''),

    source, fromNode: String(fromNode || ''), messageHash: String(messageHash || ''),

    targetBindingReceipt: String(targetBindingReceipt || ''), returnToControl: !!returnToControl,

    returnToRole: String(returnToRole || ''), hostRequestId: hostRequestId || '', fingerprint,

    createdAt: Date.now(), deliveryConfirmed: false };

  await chrome.storage.local.set({ pending: state.pending });

  let ack;

  try { ack = await sendToChatTab(reg.tabId, { type: 'relay:execute', relayId, text: payloadText }); }

  catch (error) {

    state.pending[relayId].submitUnknown = true;

    state.pending[relayId].lastTransportError = String(error?.message || error || 'RELAY_SUBMIT_UNKNOWN').slice(0, 200);

    await chrome.storage.local.set({ pending: state.pending });

    throw error;

  }

  if (!ack || !ack.ok || (ack.submitted !== true && ack.deferred !== true)) {

    delete state.pending[relayId];

    await chrome.storage.local.set({ pending: state.pending });

    throw new Error(ack?.error || 'Worker did not accept relay');

  }

  const latestState = await loadState();

  const latestPending = latestState.pending?.[relayId];

  if (!latestPending) throw new Error('RELAY_PENDING_LOST_AFTER_ACCEPT');

  latestPending.deliveryConfirmed = ack.submitted === true;

  latestPending.deferred = ack.deferred === true;

  latestPending.acceptedAt = Date.now();

  if (ack.submitted === true) latestPending.submittedAt = Date.now();

  if (bootstrapAuthorized) {

    const latestRegistration = latestState.registrations?.[role];

    if (latestRegistration && String(latestRegistration.bootstrapReceiptId || '') === String(reg.bootstrapReceiptId || '')) {

      latestRegistration.bootstrapConsumedAt = Date.now();

      latestRegistration.updatedAt = Date.now();

      latestState.registrations[role] = latestRegistration;

    }

  }

  latestState.pending[relayId] = latestPending;

  await chrome.storage.local.set({ pending: latestState.pending, registrations: latestState.registrations });

  return { ok: true, relayId, to: role, deliveryConfirmed: latestPending.deliveryConfirmed, deferred: latestPending.deferred };

}



async function deliverResult(relayId, result, senderTabId) {

  const state = await loadState();

  const pending = state.pending[relayId];

  if (!pending) {

    const existing = state.resultReceipts?.[relayId] || null;

    if (existing) {

      if (existing.returnState === 'PENDING') throw new Error('RELAY_RETURN_RECOVERY_STATE_MISSING');

      const replay = await persistDurableResultReceipt(relayId, null, result);

      return { ok: true, duplicate: replay.duplicate, resultHash: replay.receipt.resultHash,
        returnState: String(replay.receipt.returnState || '') };

    }

    const completed = (state.results || []).find((item) => String(item?.id || '') === String(relayId));

    if (completed) return { ok: true, duplicate: true };

    throw new Error('Unknown relay result');

  }

  if (pending.tabId !== senderTabId) throw new Error('Relay result came from wrong tab');

  if (pending.bootstrapCreatedTab === true) {

    const senderTab = await chrome.tabs.get(Number(senderTabId));

    const liveConversationKey = RelayCore.conversationKey(senderTab?.url || '');

    if (!liveConversationKey) throw new Error('BOOTSTRAP_CONVERSATION_ID_NOT_CAPTURED');

    if (pending.conversationKey && pending.conversationKey !== liveConversationKey) {

      throw new Error('BOOTSTRAP_CONVERSATION_IDENTITY_MISMATCH');

    }

    pending.conversationKey = liveConversationKey;

  }

  const durable = await persistDurableResultReceipt(relayId, pending, result);

  const latestState = await loadState();

  const completedAt = Date.now();

  const createdAt = Number(pending.createdAt || 0) || null;

  const acceptedAt = Number(pending.acceptedAt || 0) || null;

  const submittedAt = Number(pending.submittedAt || 0) || null;

  const networkStartedAt = Number(pending.networkStartedAt || 0) || null;

  const networkCompletedAt = Number(pending.networkCompletedAt || 0) || null;

  const timing = {

    createdAt, acceptedAt, submittedAt, networkStartedAt, networkCompletedAt, completedAt,

    deliveryMs: createdAt && networkStartedAt ? Math.max(0, networkStartedAt - createdAt) : null,

    processingMs: networkStartedAt && networkCompletedAt ? Math.max(0, networkCompletedAt - networkStartedAt) : null,

    returnMs: networkCompletedAt ? Math.max(0, completedAt - networkCompletedAt) : null,

    totalMs: createdAt ? Math.max(0, completedAt - createdAt) : null

  };

  const completedResult = {

    id: relayId,

    from: pending.to,

    ok: !!result.ok,

    reply: String(result.reply || ''),

    error: String(result.error || ''),

    fingerprint: String(pending.fingerprint || ''),

    tabId: Number(pending.tabId) || null, conversationKey: String(pending.conversationKey || ''),

    networkPath: String(pending.networkPath || ''),

    networkCandidates: Array.isArray(pending.networkCandidates) ? pending.networkCandidates : [],

    networkStartedAt, networkCompletedAt,

    networkDurationMs: timing.processingMs,

    timing,

    at: completedAt

  };

  latestState.results = (latestState.results || []).filter((item) => String(item?.id || '') !== String(relayId));

  latestState.results.unshift(completedResult);

  latestState.results = latestState.results.slice(0, 50);

  if (pending.bootstrapCreatedTab === true && latestState.operations?.[relayId]?.command === 'send-to-created-tab') {

    const operation = latestState.operations[relayId];

    operation.result = {

      ...(operation.result || {}), ok: !!result.ok, state: 'RESPONSE_COMPLETED', responsePending: false,

      conversationKey: String(pending.conversationKey || ''), tabId: Number(pending.tabId) || null,

      windowId: Number(pending.windowId) || null, reply: String(result.reply || ''),

      error: String(result.error || ''), resultHash: String(durable.receipt.resultHash || '')

    };

    operation.at = Date.now();

    latestState.operations[relayId] = operation;

  }

  await chrome.storage.local.set({ results: latestState.results, operations: latestState.operations });



  if (pending.hostRequestId) {

    postNative({

      type: 'host:result',

      requestId: pending.hostRequestId,

      relayId,

      from: pending.to,

      ok: !!result.ok,

      reply: String(result.reply || ''),

      error: String(result.error || ''),

      timing

    });

  }

  const returnRole = String(pending.returnToRole || '').trim() || (pending.returnToControl ? CONTROL : '');

  if (!returnRole) {

    const finalState = await loadState();

    if (finalState.pending?.[relayId]) delete finalState.pending[relayId];

    await chrome.storage.local.set({ pending: finalState.pending });

    return { ok: true, duplicate: durable.duplicate,

      resultHash: durable.receipt.resultHash, returnState: 'NOT_REQUESTED' };

  }

  const control = await resolveRegistration(returnRole);

  const envelope = RelayCore.makeResultEnvelope(

    pending.to,

    relayId,

    result.ok ? result.reply : `ERROR: ${result.error || 'unknown'}`

  );

  const delivery = await sendToChatTab(control.tabId, {

    type: 'relay:deliver',

    relayId,

    text: envelope

  });

  if (!delivery?.ok) throw new Error(delivery?.error || 'RELAY_RETURN_DELIVERY_NOT_ACKED');

  const returned = await markDurableReceiverDelivered(relayId);

  const finalState = await loadState();

  if (finalState.pending?.[relayId]) delete finalState.pending[relayId];

  await chrome.storage.local.set({ pending: finalState.pending });

  return { ok: true, duplicate: durable.duplicate, resultHash: durable.receipt.resultHash,
    returnState: String(returned.receipt?.returnState || ''),
    receiverAckState: String(returned.receipt?.receiverAckState || '') };

}



async function autoDirective(payload, senderTabId) {

  const state = await loadState();

  const control = state.registrations[CONTROL];

  if (!control || control.tabId !== senderTabId) throw new Error('Directive not from CONTROL');

  if (!state.settings.armed || state.settings.budget <= 0) throw new Error('Auto relay is not armed');

  if (payload.token !== state.settings.token) throw new Error('Bad relay token');

  const relayId = payload.id || crypto.randomUUID();

  if (state.processed.includes(relayId)) throw new Error('Duplicate relay id');

  state.processed.unshift(relayId);

  state.processed = state.processed.slice(0, 100);

  state.settings.budget -= 1;

  if (state.settings.budget <= 0) state.settings.armed = false;

  await chrome.storage.local.set({ processed: state.processed, settings: state.settings });

  return dispatchRelay({ to: payload.to, text: payload.text, id: relayId, source: 'control', returnToControl: true });

}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  (async () => {

    if (message.type === 'relay:actDirectTask') return requestActDirectTask(sender, message.directive);

    if (message.type === 'relay:actLocalExecution') return requestActLocalExecution(sender, message.directive);

    if (message.type === 'relay:actWorkerOperation') return requestActWorkerOperation(sender, message.directive);

    if (message.type === 'relay:actNaturalCommand') return requestActNaturalCommand(sender, message.text);

    if (message.type === 'relay:actBootstrapResync') {

      if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !isChatTab(sender.tab)) throw new Error('ACT_UNTRUSTED_SENDER');

      return requestActBootstrapResync(sender.tab);

    }

    if (message.type === 'relay:forceRefresh') return forceRelayRefresh('manual-refresh');

    if (message.type === 'relay:authorizeInjection') {
      return authorizeInjectionSender(sender, message.conversationKey);
    }

    if (message.type === 'relay:getPendingStatus') {

      const state = await loadState();

      const relayId = String(message.relayId || '');

      const pending = state.pending?.[relayId];

      const tabId = Number(sender.tab?.id);

      if (!pending || Number(pending.tabId) !== tabId) return { ok: false, found: false };

      const key = RelayCore.conversationKey(sender.tab?.url || '');

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

      return { ok: true, tabs, registrations: state.registrations, settings: state.settings, results: state.results };

    }

    if (message.type === 'relay:register') {

      return { ok: true, registration: await registerRole(message.role, message.tabId) };

    }

    if (message.type === 'relay:arm') {

      const state = await loadState();

      state.settings.armed = !!message.armed;

      state.settings.budget = state.settings.armed ? Math.max(1, Math.min(Number(message.budget) || 6, 12)) : 0;

      await chrome.storage.local.set({ settings: state.settings });

      await notifyRelayLocalState();

      return { ok: true, settings: state.settings };

    }

    if (message.type === 'relay:manualSend') {

      return dispatchRelay({ to: message.to, text: message.text, source: 'popup', returnToControl: !!message.returnToControl });

    }

    if (message.type === 'relay:bootstrap') {

      const state = await loadState();

      const control = await resolveRegistration(CONTROL);

      const reply = await sendToChatTab(control.tabId, { type: 'relay:bootstrap', token: state.settings.token });

      return reply || { ok: false, error: 'No bootstrap response' };

    }

    if (message.type === 'relay:hello') {

      const state = await loadState();

      const tabId = sender.tab?.id;

      const key = RelayCore.conversationKey(sender.tab?.url || message.url || '');

      let role = null;

      for (const [name, reg] of Object.entries(state.registrations)) {

        const keyMatches = !!(reg.conversationKey && key && reg.conversationKey === key);

        const legacyTabMatches = !reg.conversationKey && reg.tabId === tabId;

        if (keyMatches || legacyTabMatches) {

          role = name;

          if (key && !reg.conversationKey && reg.authorization === 'ACT_CONVERSATION_BOOTSTRAP') {

            reg.bootstrapConversationKey = key;

            reg.updatedAt = Date.now();

            state.registrations[name] = reg;

            await chrome.storage.local.set({ registrations: state.registrations });

          }

          if (tabId && reg.tabId !== tabId) {

            reg.tabId = tabId;

            reg.updatedAt = Date.now();

            state.registrations[name] = reg;

            await chrome.storage.local.set({ registrations: state.registrations });

          }

          break;

        }

      }

      return { ok: true, role, armed: !!state.settings.armed, budget: state.settings.budget || 0,

        markerScanEnabled: !!state.settings.armed };

    }

    if (message.type === 'relay:returnDelivered') {
      const relayId = String(message.relayId || '').trim();
      const confirmed = await confirmDurableReceiverDelivery(sender, relayId);
      return { ok: true, relayId, returnState: String(confirmed.receipt?.returnState || ''),
        receiverAckState: String(confirmed.receipt?.receiverAckState || ''),
        duplicate: confirmed.duplicate === true };
    }

    if (message.type === 'relay:deliveryReady') {
      await endpointSessionReady;
      const tab = sender.tab;
      if (!isChatTab(tab) || tab?.id == null) {
        return { ok: false, error: 'DELIVERY_READY_SOURCE_NOT_CHAT_TAB' };
      }
      const state = await loadState();
      const conversationKey = RelayCore.conversationKey(tab.url || '');
      if (!conversationKey || conversationKey !== String(message.conversationKey || '')) {
        return { ok: false, error: 'DELIVERY_READY_CONVERSATION_MISMATCH' };
      }
      const authorized = Object.values(state.registrations || {}).some((registration) =>
        Number(registration?.tabId) === Number(tab.id)
        && String(registration?.conversationKey || '') === conversationKey
        && (registrationHasDynamicAuthorization(registration, state)
          || registrationHasBootstrapAuthorization(registration, state)));
      if (!authorized) return { ok: true, attempted: false, reason: 'DELIVERY_READY_UNBOUND' };
      return { ok: true, ...(await retryPendingResultReturnForTab(tab.id)) };
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

    if (message.type === 'relay:autoDirective') {

      return autoDirective(message.directive, sender.tab?.id);

    }

    if (message.type === 'relay:workerResult') {

      return deliverResult(message.relayId, message.result || {}, sender.tab?.id);

    }

    throw new Error(`Unknown message type: ${message.type}`);

  })().then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));

  return true;

});



installRelayNetworkListeners();

connectNativeHost();

chrome.runtime.onStartup.addListener(() => connectNativeHost());

chrome.runtime.onInstalled.addListener(() => connectNativeHost());

chrome.tabs.onCreated?.addListener((tab) => { handleEndpointTabCreated(tab).catch(() => {}); });

chrome.tabs.onUpdated?.addListener((tabId, changeInfo, tab) => { handleEndpointTabUpdated(tabId, changeInfo, tab).catch(() => {}); });

chrome.tabs.onRemoved?.addListener((tabId) => { handleEndpointTabRemoved(tabId).catch(() => {}); });
