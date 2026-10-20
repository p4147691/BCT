const CHAT_URLS = ['https://chatgpt.com/*', 'https://chat.openai.com/*'];
const stateRepository = RccChromeStateRepository.create(chrome, () => crypto.randomUUID());
const browserGateway = RccBrowserGateway.create(chrome, {
  chatUrls: CHAT_URLS,
  receiverFiles: ['relay_core.js', 'content.js'],
});
const observationGateway = RccObservationGateway.create(chrome);
const lifecycle = RccLifecycle.create(chrome);

const CONTROL = 'CONTROL';

const NATIVE_HOST = 'com.ai_workspace_relay.host';

const RCC_BACKGROUND_BUILD_ID = '2026-10-20-rcc-core-shadow-v1';

const RELAY_RESULT_RECEIPTS_KEY = 'relayResultReceiptsV1';
// Generic completed operations are an idempotency cache and are intentionally
// bounded.  Rename recovery is different: an UNKNOWN rename must be
// inspectable long after unrelated operations have displaced that cache.
// These compact, terminal records are therefore never pruned automatically.
// They may only be removed by a future explicit, authenticated retention
// protocol after BCT has durably established a terminal outcome.
const RENAME_RECEIPTS_KEY = 'renameReceiptsV1';
const BINDING_SUBMIT_LEASES_KEY = 'bindingSubmitLeasesV1';
// V0 is deliberately independent from the legacy role/lease registry.  It is
// only an address book for one Manager and one Worker plus compact delivery
// receipts; it never creates nodes, queues work, or promotes replies.
const SIMPLE_RELAY_V0_BINDING_KEY = 'simpleRelayV0Binding';
const SIMPLE_RELAY_V0_RECEIPTS_KEY = 'simpleRelayV0Receipts';

let bindingLeaseMutationChain = Promise.resolve();

let nativeTransport = null;

const endpointPresence = new Map();

const ENDPOINT_SESSION_STORAGE_KEY = 'rccEndpointSessionIdV1';
let endpointSessionId = '';
const endpointSessionReady = (async () => {
  endpointSessionId = await stateRepository.getOrCreateSessionId(ENDPOINT_SESSION_STORAGE_KEY);
  return endpointSessionId;
})();


async function loadState() {

  const data = await stateRepository.getLocal(['registrations', 'settings', 'pending', 'results', 'processed', 'operations', RELAY_RESULT_RECEIPTS_KEY, RENAME_RECEIPTS_KEY, BINDING_SUBMIT_LEASES_KEY, SIMPLE_RELAY_V0_BINDING_KEY]);

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

  if (settingsDirty) await stateRepository.setLocal({ settings });

  return {

    registrations: data.registrations || {},

    settings,

    pending: data.pending || {},

    results: data.results || [],

    processed: data.processed || [],

    operations: data.operations || {},

    resultReceipts: data[RELAY_RESULT_RECEIPTS_KEY] || {},

    renameReceipts: data[RENAME_RECEIPTS_KEY] || {},

    bindingSubmitLeases: data[BINDING_SUBMIT_LEASES_KEY] || {},

    simpleRelayV0Binding: data[SIMPLE_RELAY_V0_BINDING_KEY] || null

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
async function getChatTabs() {
  return browserGateway.queryChatTabs();

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
  return browserGateway.publicTab(tab);

}

function coreShadowSnapshot(tabs, endpoints, binding) {
  try {
    return RccCoreShadow.snapshot({ tabs, endpoints, binding });
  } catch (error) {
    return {
      schemaVersion: 1,
      mode: 'READ_ONLY_SHADOW',
      status: 'PROTOCOL_MISMATCH',
      matches: false,
      error: String(error?.message || error || 'RCC_CORE_SHADOW_FAILED').slice(0, 160),
    };
  }
}


function isChatTab(tab) {
  return browserGateway.isChatTab(tab);

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

    const win = await browserGateway.getWindow(windowId);

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

    const probe = await browserGateway.probeActivity(tab.id);

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


async function recoverCompletedReplyDirectlyFromTab(tabId, conversationKey, submittedText) {
  const tab = await browserGateway.getExactTab(tabId);
  if (!isChatTab(tab) || RelayCore.conversationKey(tab.url || '') !== String(conversationKey || '')) {
    throw new Error('RELAY_RECOVERY_DIRECT_IDENTITY_MISMATCH');
  }
  const injected = await browserGateway.executeScript({
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
        const keyedDescendants = Array.from(node.querySelectorAll?.('[data-turn-key]') || []);
        const turn = node.matches('[data-turn-key]')
          ? node
          : (node.closest('[data-turn-key]')
            || (keyedDescendants.length === 1 ? keyedDescendants[0] : node));
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
        // Keep this exact UI-decoration rule aligned with messageUnitText.
        clone.querySelectorAll('[data-search-result-target] + span[aria-hidden="true"]').forEach((item) => {
          if (item.textContent === '…') item.remove();
        });
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

function bindingLeaseTargetsConflict(lease, target) {
  if (!lease || !target) return false;
  return (!!target.role && String(lease.role || '') === String(target.role || ''))
    || (Number(target.tabId || 0) > 0 && Number(lease.tabId || 0) === Number(target.tabId || 0))
    || (!!target.conversationKey
      && String(lease.conversationKey || '') === String(target.conversationKey || ''));
}

function pruneExpiredBindingSubmitLeases(state, now = Date.now()) {
  const leases = state.bindingSubmitLeases || {};
  let changed = false;
  for (const [leaseId, lease] of Object.entries(leases)) {
    if (Number(lease?.expiresAt || 0) <= now) {
      delete leases[leaseId];
      changed = true;
    }
  }
  state.bindingSubmitLeases = leases;
  return changed;
}

function withBindingLeaseMutation(work) {
  const next = bindingLeaseMutationChain.catch(() => {}).then(work);
  bindingLeaseMutationChain = next.catch(() => {});
  return next;
}

async function mutateRegistrationsWithLeaseFence(targets, mutation) {
  return withBindingLeaseMutation(async () => {
    const state = await loadState();
    pruneExpiredBindingSubmitLeases(state);
    const targetList = (Array.isArray(targets) ? targets : [targets]).filter(Boolean);
    const conflict = Object.values(state.bindingSubmitLeases || {}).some((lease) =>
      targetList.some((target) => bindingLeaseTargetsConflict(lease, target)));
    if (conflict) throw new Error('PRE_SUBMIT_BINDING_LEASE_ACTIVE');
    const result = await mutation(state);
    await stateRepository.setLocal({
      registrations: state.registrations,
      [BINDING_SUBMIT_LEASES_KEY]: state.bindingSubmitLeases || {}
    });
    return result;
  });
}

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


// Exact operator-selected tab: one-call registration and first send.
// Promote an already-bound backup only after ACT has proved that the former
// manager endpoint is no longer live. This never sends a chat message.
function postNative(message) {
  nativeTransport?.post(message);

}


async function handleNativeCommand(message) {
  await endpointSessionReady;
  if (message?.type !== 'host:command') return;
  const requestId = String(message.requestId || crypto.randomUUID());
  const commandDecision = RccLegacyCommandPolicy.nativeCommand(message.command);
  if (!commandDecision.allowed) {
    postNative({ type: 'host:result', requestId, ok: false, effectState: 'NOT_APPLIED',
      error: RccLegacyCommandPolicy.rejectCode('NATIVE_COMMAND', message.command, commandDecision) });
    return;
  }
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


          const coreShadow = coreShadowSnapshot(tabs, endpoints, state.simpleRelayV0Binding);


          postNative({ type: 'host:result', requestId, ok: true, state: {


            instanceId: state.settings.instanceId, sessionId: endpointSessionId, tabs, endpoints,


            registrations: state.registrations, settings: state.settings,


            simpleRelayV0Binding: state.simpleRelayV0Binding,


            coreShadow,


            backgroundBuildId: RCC_BACKGROUND_BUILD_ID


          } });


          return;


        }

    if (message.command === 'simple-relay-bind') {

          const result = await bindSimpleRelayV0(message);

          postNative({ type: 'host:result', requestId, ...result });

          return;

        }

    if (message.command === 'simple-relay-send') {

          const result = await sendSimpleRelayV0(message, requestId);

          postNative({ type: 'host:result', requestId, ...result,

            relayReceipt: publicSimpleRelayV0Receipt(result.receipt) });

          return;

        }

    if (message.command === 'simple-relay-return') {

          const result = await returnSimpleRelayV0(message, requestId);

          postNative({ type: 'host:result', requestId, ...result,

            relayReceipt: publicSimpleRelayV0Receipt(result.receipt) });

          return;

        }

    if (message.command === 'rename-receipt') {

          // Inspection only: never perform or repeat an effect here.

          const relayId = String(message.text || '').trim();

          const tabId = Number(message.tabId);

          const conversationKey = String(message.conversationKey || '');

          if (!relayId || !Number.isSafeInteger(tabId) || tabId <= 0 || !conversationKey) {

            throw new Error('RENAME_RECEIPT_IDENTITY_REQUIRED');

          }

          const state = await loadState();

          // `operations` is a short generic idempotency cache.  Prefer the

          // dedicated rename ledger so unrelated traffic cannot erase recovery

          // evidence, while preserving compatibility with receipts recorded by

          // earlier builds.

          const dedicatedRenameReceipt = state.renameReceipts?.[relayId] || null;

          const record = dedicatedRenameReceipt || state.operations?.[relayId] || null;

          // A reservation contains caller-controlled expected fields so it can

          // reserve storage before UI dispatch.  It is not a terminal receipt and

          // must never be exposed as proof to Core reconciliation.

          const terminal = dedicatedRenameReceipt

            ? dedicatedRenameReceipt.terminal === true : Boolean(record);

          const tab = await browserGateway.getExactTab(tabId).catch(() => null);

          const observed = tab ? {

            tabId: tab.id,

            conversationKey: RelayCore.conversationKey(String(tab.url || '')),

            title: String(tab.title || ''),

            presence: isChatTab(tab) ? 'OPEN' : 'UNKNOWN',

            currentSessionId: endpointSessionId,

          } : null;

          postNative({ type: 'host:result', requestId, ok: true,

            instanceId: state.settings.instanceId, relayId,

            receipt: terminal && record ? { command: record.command,

              fingerprint: record.fingerprint, result: record.result } : null,

            receiptState: terminal ? 'TERMINAL' : (record ? 'PREPARED' : 'MISSING'),

            observed });

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

    if (message.command === 'main-capture-get') {


          const reg=await resolveRegistration(message.to); const x=await browserGateway.executeScript({target:{tabId:reg.tabId},world:'MAIN',func:()=>window.__dwRelayCaptured||[]}); postNative({type:'host:result',requestId,ok:true,captured:x?.[0]?.result||[]}); return;


        }

    if (message.command === 'api-probe') {


          const reg = await resolveRegistration(message.to);


          const key = String(reg.conversationKey || '');


          const injected = await browserGateway.executeScript({ target: { tabId: reg.tabId }, func: async (conversationKey) => {


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

              probe = await browserGateway.sendMessage(tab.id, { type: 'relay:probe' });

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


              const result = await browserGateway.executeScript({ target: { tabId: tab.id }, func: () => {


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

              const result = await browserGateway.executeScript({

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

              const data = await stateRepository.getLocal([RELAY_RESULT_RECEIPTS_KEY]);

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

                const compare = await browserGateway.executeScript({

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

              const result = await browserGateway.executeScript({

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

    if (message.command === 'reload-extension') {


          postNative({ type: 'host:result', requestId, ok: true, reloading: true });


          lifecycle.reload(50);


          return;


        }
    throw new Error(`Unknown native command: ${message.command}`);
  } catch (error) {
    postNative({ type: 'host:result', requestId, ok: false, error: error.message });
  }
}


async function connectNativeHost() {
  return nativeTransport.connect();

}

async function handleNativeConnected(connection) {
  const state = await loadState();
  postNative({ type: 'host:ready', extensionId: connection.extensionId,
    instanceId: state.settings.instanceId });
  (async () => {
    const tabs = (await getChatTabs()).filter(isChatTab);
    await ensureRelayReceivers(tabs);
    await publishEndpointSnapshot('native-connect', tabs);
  })().catch(() => {});
}


async function resolveRegistration(roleValue) {

  const role = RelayCore.normalizeRole(roleValue);

  const state = await loadState();

  const reg = state.registrations[role];

  if (!reg) throw new Error(`Role not registered: ${role}`);

  if (reg.tabId) {

    try {

      const tab = await browserGateway.getExactTab(reg.tabId);

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

  return mutateRegistrationsWithLeaseFence(
    [{ role }, reg, { tabId: match.id, conversationKey: reg.conversationKey }],
    async (latest) => {
      const current = latest.registrations?.[role];
      if (!current || String(current.conversationKey || '') !== String(reg.conversationKey || '')) {
        throw new Error(`Registered conversation changed for ${role}`);
      }
      current.tabId = match.id;
      current.title = match.title || current.title;
      current.updatedAt = Date.now();
      latest.registrations[role] = current;
      return { ...current };
    }
  );

}

function handleRuntimeMessage(message, sender, sendResponse) {
  (async () => {
    const messageDecision = RccLegacyCommandPolicy.runtimeMessage(message?.type);
    if (!messageDecision.allowed) throw new Error(RccLegacyCommandPolicy.rejectCode('RUNTIME_MESSAGE', message?.type, messageDecision));
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


          return { ok: true, tabs, registrations: state.registrations, settings: state.settings, results: state.results };


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
    throw new Error(`Unknown message type: ${message.type}`);
  })().then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));
  return true;
}

nativeTransport = RccNativeTransport.create(chrome, {
  hostName: NATIVE_HOST,
  reconnectDelayMs: 3000,
  onMessage: handleNativeCommand,
  onConnected: handleNativeConnected,
});
lifecycle.registerRuntimeMessage(handleRuntimeMessage);
lifecycle.registerStartup(() => connectNativeHost());
observationGateway.registerTabListeners({
  onCreated: (tab) => { handleEndpointTabCreated(tab).catch(() => {}); },
  onUpdated: (tabId, changeInfo, tab) => {
    handleEndpointTabUpdated(tabId, changeInfo, tab).catch(() => {});
  },
  onRemoved: (tabId) => { handleEndpointTabRemoved(tabId).catch(() => {}); },
});
connectNativeHost();
