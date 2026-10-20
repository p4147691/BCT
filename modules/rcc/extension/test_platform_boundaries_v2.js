const assert = require('assert');
const StateRepository = require('./platform/chrome_state_repository.js');
const BrowserGateway = require('./platform/browser_gateway.js');
const NativeTransport = require('./platform/native_transport.js');
const ObservationGateway = require('./platform/observation_gateway.js');
const Lifecycle = require('./platform/lifecycle.js');

const listeners = {};
const local = { settings: { instanceId: 'a'.repeat(32) } };
const session = {};
const tab = { id: 7, windowId: 9, url: 'https://chatgpt.com/c/exact', title: 'Exact' };
let sendCalls = 0;
let receiverReady = false;
let reloadCalls = 0;
const nativePosts = [];
const chrome = {
  storage: {
    local: {
      get: async (keys) => typeof keys === 'string' ? { [keys]: local[keys] } : { ...local },
      set: async (patch) => Object.assign(local, patch),
    },
    session: {
      get: async (keys) => Object.fromEntries(keys.filter((key) => key in session).map((key) => [key, session[key]])),
      set: async (patch) => Object.assign(session, patch),
    },
  },
  tabs: {
    query: async () => [tab, { id: 8, url: 'https://example.com/' }],
    get: async (id) => { assert.equal(id, tab.id); return tab; },
    sendMessage: async (_id, message) => {
      sendCalls += 1;
      if (message.type === 'relay:activityProbe') return { ok: true, generating: false };
      if (sendCalls === 1) throw new Error('Could not establish connection. Receiving end does not exist.');
      return { ok: true, echoedType: message.type };
    },
    onCreated: { addListener: (fn) => { listeners.created = fn; } },
    onUpdated: { addListener: (fn) => { listeners.updated = fn; } },
    onRemoved: { addListener: (fn) => { listeners.removed = fn; } },
  },
  windows: { get: async () => ({ id: 9, state: 'normal' }) },
  scripting: {
    executeScript: async (spec) => {
      if (spec.func) return [{ result: receiverReady }];
      assert.deepEqual(spec.files, ['relay_core.js', 'content.js']);
      receiverReady = true;
      return [];
    },
  },
  runtime: {
    id: 'extension-id',
    connectNative: (host) => {
      assert.equal(host, 'com.ai_workspace_relay.host');
      return {
        postMessage: (value) => nativePosts.push(value),
        onMessage: { addListener: (fn) => { listeners.nativeMessage = fn; } },
        onDisconnect: { addListener: (fn) => { listeners.nativeDisconnect = fn; } },
      };
    },
    onMessage: { addListener: (fn) => { listeners.runtimeMessage = fn; } },
    onStartup: { addListener: (fn) => { listeners.startup = fn; } },
    onInstalled: { addListener: (fn) => { listeners.installed = fn; } },
    reload: () => { reloadCalls += 1; },
  },
};

(async () => {
  const repository = StateRepository.create(chrome, () => '12345678123456781234567812345678');
  assert.equal(await repository.getOrCreateSessionId('session'), '12345678123456781234567812345678');
  assert.equal(session.session, '12345678123456781234567812345678');
  await repository.setLocal({ receipt: { state: 'SUBMITTED' } });
  assert.equal((await repository.getLocal('receipt')).receipt.state, 'SUBMITTED');

  const browser = BrowserGateway.create(chrome, {
    chatUrls: ['https://chatgpt.com/*'], receiverFiles: ['relay_core.js', 'content.js'],
  });
  assert.deepEqual((await browser.queryChatTabs()).map((item) => item.id), [7]);
  assert.equal((await browser.getExactTab(7)).url, tab.url);
  assert.equal((await browser.sendWithReceiver(7, { type: 'relay:simpleExecute' })).ok, true);
  assert.equal(sendCalls, 2, 'missing receiver must inject once and retry once');
  assert.equal(receiverReady, true);

  let connected = null;
  const transport = NativeTransport.create(chrome, {
    hostName: 'com.ai_workspace_relay.host', reconnectDelayMs: 1,
    onMessage: (message) => { listeners.received = message; },
    onConnected: (value) => { connected = value; },
  });
  await transport.connect();
  assert.deepEqual(connected, { extensionId: 'extension-id' });
  transport.post({ type: 'host:ready' });
  assert.deepEqual(nativePosts, [{ type: 'host:ready' }]);

  const observed = [];
  ObservationGateway.create(chrome).registerTabListeners({
    onCreated: (value) => observed.push(['created', value.id]),
    onUpdated: (id) => observed.push(['updated', id]),
    onRemoved: (id) => observed.push(['removed', id]),
  });
  listeners.created(tab); listeners.updated(7, {}, tab); listeners.removed(7, {});
  assert.deepEqual(observed, [['created', 7], ['updated', 7], ['removed', 7]]);

  const lifecycle = Lifecycle.create(chrome);
  lifecycle.registerRuntimeMessage(() => true);
  lifecycle.registerStartup(() => {});
  assert.equal(typeof listeners.runtimeMessage, 'function');
  assert.equal(typeof listeners.startup, 'function');
  assert.equal(typeof listeners.installed, 'function');
  lifecycle.reload(0);
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(reloadCalls, 1);
  console.log('rcc platform boundaries v2: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
