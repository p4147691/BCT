const endpointPresence = new Map();

const ENDPOINT_SESSION_STORAGE_KEY = 'rccEndpointSessionIdV1';
let endpointSessionId = '';
const endpointSessionReady = (async () => {
  endpointSessionId = await stateRepository.getOrCreateSessionId(ENDPOINT_SESSION_STORAGE_KEY);
  return endpointSessionId;
})();

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

    tabIndex: Number.isInteger(tab?.index) ? tab.index : null,

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

    endpoint?.tabIndex ?? null,

    endpoint?.conversationKey || '',

    endpoint?.title || '',

    endpoint?.url || '',

    endpoint?.reasoning ? JSON.stringify(endpoint.reasoning) : '',

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

    endpoint.reasoning = probe?.reasoning && typeof probe.reasoning === 'object'
      ? probe.reasoning : null;

    endpoint.telemetry = probe?.telemetry && typeof probe.telemetry === 'object' ? probe.telemetry : null;
    endpoint.connection = probe?.connection && typeof probe.connection === 'object' ? probe.connection : null;

  } catch (_) {

    const previous = endpointPresence.get(tab.id);

    if (typeof previous?.generating === 'boolean') endpoint.generating = previous.generating;

    if (previous?.reasoning && typeof previous.reasoning === 'object') {
      endpoint.reasoning = previous.reasoning;
    }

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

    if (!endpoint.reasoning && prior?.reasoning && typeof prior.reasoning === 'object') {
      endpoint.reasoning = prior.reasoning;
    }

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

async function handleEndpointTabMoved(_tabId) {

  // Moving any tab shifts every later Chrome tab index in the same window.
  // Publish one complete snapshot instead of leaving sibling ChatGPT indices
  // stale until the next explicit state read.
  await publishEndpointSnapshot('moved');

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
