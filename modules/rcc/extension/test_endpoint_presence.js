const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { randomUUID } = require('crypto');

const source = fs.readFileSync('background.js', 'utf8');

function conversationKey(url) {
  try {
    const match = new URL(url).pathname.match(/\/c\/([a-z0-9-]+)/i);
    return match ? match[1] : '';
  } catch { return ''; }
}

function makeHarness(initialTabs) {
  let tabs = initialTabs.map((tab) => ({ ...tab }));
  const nativeMessages = [];
  let nativeListener = null;
  let createdListener = null;
  let updatedListener = null;
  let removedListener = null;
  let queryCount = 0;
  const store = {
    registrations: {},
    settings: { token: 'test-token', armed: false, budget: 0, instanceId: 'presenceinstance1234' },
    pending: {}, results: [], processed: []
  };
  const port = {
    onMessage: { addListener(fn) { nativeListener = fn; } },
    onDisconnect: { addListener() {} },
    postMessage(message) { nativeMessages.push(JSON.parse(JSON.stringify(message))); }
  };
  const chrome = {
    storage: { local: {
      get: async () => store,
      set: async (patch) => Object.assign(store, patch)
    } },
    tabs: {
      query: async () => {
        queryCount += 1;
        return tabs.filter((tab) => /^https:\/\/(chatgpt\.com|chat\.openai\.com)\//i.test(tab.url || ''));
      },
      get: async (id) => {
        const tab = tabs.find((item) => item.id === Number(id));
        if (!tab) throw new Error('tab not found');
        return tab;
      },
      create: async ({ url, active }) => {
        const tab = { id: 100 + tabs.length, windowId: 9, url, title: '', active: !!active };
        tabs.push(tab);
        return tab;
      },
      sendMessage: async () => ({ ok: true }),
      onCreated: { addListener(fn) { createdListener = fn; } },
      onUpdated: { addListener(fn) { updatedListener = fn; } },
      onRemoved: { addListener(fn) { removedListener = fn; } }
    },
    scripting: { executeScript: async () => {} },
    runtime: {
      id: 'test-extension',
      onMessage: { addListener() {} },
      connectNative: () => port,
      onStartup: { addListener() {} },
      onInstalled: { addListener() {} }
    }
  };
  const context = {
    console, URL, setTimeout, clearTimeout, setInterval: () => 0, clearInterval: () => {},
    crypto: { randomUUID },
    RelayCore: {
      normalizeRole: (value) => String(value || '').trim().toUpperCase(),
      conversationKey,
      makeResultEnvelope: () => ''
    },
    chrome
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: 'background.js' });

  return {
    nativeMessages,
    queryCount() { return queryCount; },
    async forceRefresh() {
      const before = queryCount;
      const result = await context.forceRelayRefresh('test-refresh');
      await this.settle();
      return { result, queryDelta: queryCount - before };
    },
    async settle() { await new Promise((resolve) => setTimeout(resolve, 10)); },
    async created(tab) { tabs.push({ ...tab }); createdListener(tab); await this.settle(); },
    async updated(tabId, patch) {
      const tab = tabs.find((item) => item.id === tabId);
      Object.assign(tab, patch);
      updatedListener(tabId, patch, { ...tab });
      await this.settle();
    },
    async removed(tabId) {
      removedListener(tabId, { windowId: tabs.find((item) => item.id === tabId)?.windowId });
      tabs = tabs.filter((item) => item.id !== tabId);
      await this.settle();
    },
    async nativeCommand(command, to = '', text = '') {
      const requestId = `req-${command}`;
      nativeListener({ type: 'host:command', requestId, command, to, text });
      await this.settle();
      return nativeMessages.findLast((message) => message.requestId === requestId);
    },
    async activityBridgeConcurrency(count = 9) {
      let active = 0;
      let maxActive = 0;
      let calls = 0;
      const original = chrome.scripting.executeScript;
      chrome.scripting.executeScript = async () => {
        calls += 1;
        active += 1;
        maxActive = Math.max(maxActive, active);
        await new Promise((resolve) => setTimeout(resolve, 5));
        active -= 1;
      };
      try {
        const syntheticTabs = Array.from({ length: count }, (_, index) => ({
          id: 1000 + index,
          windowId: 100,
          url: `https://chatgpt.com/c/concurrency-${index}`,
          title: `Concurrency ${index}`
        }));
        await context.ensureActivityBridges(syntheticTabs);
      } finally {
        chrome.scripting.executeScript = original;
      }
      return { calls, maxActive };
    }
  };
}

function endpointMessages(messages) {
  return messages.filter((message) => message.type === 'host:endpoints');
}

(async () => {
  const h = makeHarness([
    { id: 1, windowId: 10, url: 'https://chatgpt.com/c/same-conversation', title: 'A' },
    { id: 2, windowId: 11, url: 'https://chatgpt.com/c/same-conversation', title: 'B' },
    { id: 3, windowId: 12, url: 'https://example.com/', title: 'Not ChatGPT' }
  ]);
  await h.settle();
  assert.strictEqual(h.queryCount(), 1, 'native-connect should use one ChatGPT tab query');

  const startup = endpointMessages(h.nativeMessages).find((message) => message.mode === 'snapshot');
  assert(startup, 'startup snapshot missing');
  assert.strictEqual(startup.endpoints.length, 2);
  assert.deepStrictEqual(startup.endpoints.map((endpoint) => endpoint.tabId).sort(), [1, 2]);
  assert(startup.endpoints.every((endpoint) => endpoint.conversationKey === 'same-conversation'));
  assert(startup.endpoints.every((endpoint) => endpoint.presence === 'OPEN'));

  const beforeStateQuery = h.queryCount();
  const stateResult = await h.nativeCommand('state');
  assert.strictEqual(stateResult.ok, true);
  assert.match(stateResult.state.sessionId, /^[a-f0-9]{32}$/i,
    'state must expose the exact endpoint session used by mutations');
  assert.strictEqual(h.queryCount() - beforeStateQuery, 1, 'state should reuse one ChatGPT tab snapshot');

  const refresh = await h.forceRefresh();
  assert.strictEqual(refresh.result.ok, true);
  assert.strictEqual(refresh.queryDelta, 1, 'force refresh should reuse one ChatGPT tab snapshot');

  const concurrency = await h.activityBridgeConcurrency(9);
  assert.strictEqual(concurrency.calls, 9, 'all synthetic tabs must be processed');
  assert(concurrency.maxActive > 1, 'tab bridge work should run concurrently');
  assert(concurrency.maxActive <= 4, 'tab bridge work must stay bounded to four concurrent tasks');

  await h.created({ id: 4, windowId: 13, url: 'https://chatgpt.com/c/new-conversation', title: 'New' });
  let deltas = endpointMessages(h.nativeMessages).filter((message) => message.mode === 'delta');
  assert(deltas.some((message) => message.endpoints[0].tabId === 4 && message.endpoints[0].presence === 'OPEN'));

  await h.updated(4, { url: 'https://example.com/' });
  deltas = endpointMessages(h.nativeMessages).filter((message) => message.mode === 'delta');
  assert(deltas.some((message) => message.endpoints[0].tabId === 4 &&
    message.endpoints[0].presence === 'OFFLINE' && message.endpoints[0].reason === 'navigated-away'));

  await h.removed(1);
  deltas = endpointMessages(h.nativeMessages).filter((message) => message.mode === 'delta');
  assert(deltas.some((message) => message.endpoints[0].tabId === 1 &&
    message.endpoints[0].presence === 'OFFLINE' && message.endpoints[0].reason === 'removed'));

  const ensure = await h.nativeCommand('ensure', 'SOURCE', 'restored-conversation');
  assert.strictEqual(ensure.ok, true);
  assert.strictEqual(ensure.registration.conversationKey, 'restored-conversation');

  const restarted = makeHarness([
    { id: 77, windowId: 21, url: 'https://chatgpt.com/c/restored-conversation', title: 'Restored' }
  ]);
  await restarted.settle();
  const restartSnapshot = endpointMessages(restarted.nativeMessages).find((message) => message.mode === 'snapshot');
  assert.strictEqual(restartSnapshot.endpoints.length, 1);
  assert.strictEqual(restartSnapshot.endpoints[0].tabId, 77);
  console.log('endpoint presence tests: PASS (startup/delta/offline/duplicate/restart/ensure/query-budget/bounded-concurrency)');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
