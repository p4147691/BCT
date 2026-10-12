const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { randomUUID } = require('crypto');

const source =
  fs.readFileSync('background.js', 'utf8') + '\n' +
  fs.readFileSync('act_bridge.js', 'utf8') +
  '\n;globalThis.__bootstrapTest = { requestActBootstrapResync, acceptActNativeResult };';

function conversationKey(url) {
  try {
    const match = new URL(url).pathname.match(/\/c\/([a-z0-9-]+)/i);
    return match ? match[1] : '';
  } catch { return ''; }
}

function makeHarness(responseFactory) {
  const tab = { id: 7, windowId: 1, url: 'https://chatgpt.com/c/fresh-key', title: 'Fresh', active: true };
  const store = {
    registrations: {},
    settings: { token: 't', instanceId: 'instance1234', armed: false, budget: 0 },
    pending: {}, results: [], processed: [], operations: {}
  };
  const nativeMessages = [];
  let context = null;

  const port = {
    onMessage: { addListener() {} },
    onDisconnect: { addListener() {} },
    postMessage(message) {
      nativeMessages.push(message);
      if (message?.type !== 'host:act') return;
      const response = responseFactory(message);
      setTimeout(() => {
        context.__bootstrapTest.acceptActNativeResult({
          type: 'host:act-result',
          requestId: message.requestId,
          response
        });
      }, 0);
    }
  };

  const chrome = {
    storage: { local: { get: async () => store, set: async (x) => Object.assign(store, x) } },
    tabs: {
      query: async () => [tab],
      get: async () => ({ ...tab }),
      sendMessage: async () => ({ ok: true, generating: false }),
      onCreated: { addListener() {} },
      onUpdated: { addListener() {} },
      onRemoved: { addListener() {} }
    },
    windows: {
      get: async () => ({ left: 0, top: 0, width: 100, height: 100, state: 'normal', focused: true }),
      onFocusChanged: { addListener() {} }
    },
    scripting: { executeScript: async () => [{ result: [] }] },
    webRequest: {
      onBeforeRequest: { addListener() {} },
      onCompleted: { addListener() {} },
      onErrorOccurred: { addListener() {} }
    },
    runtime: {
      id: 'test',
      connectNative: () => port,
      onMessage: { addListener() {} },
      onStartup: { addListener() {} },
      onInstalled: { addListener() {} }
    }
  };

  context = {
    console, URL, JSON, setTimeout, clearTimeout,
    setInterval: () => 0, clearInterval: () => {},
    crypto: { randomUUID },
    RelayCore: {
      conversationKey,
      normalizeRole: (v) => String(v || '').trim().toUpperCase(),
      makeResultEnvelope: () => ''
    },
    chrome
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: 'rcc-bootstrap-current.js' });

  return {
    tab,
    nativeMessages,
    request: context.__bootstrapTest.requestActBootstrapResync
  };
}

function validBootstrapResponse(message) {
  const caller = message.caller;
  return {
    ok: true,
    self: { conversation_key: caller.conversation_key, generation: 7 },
    bootstrap_contract: {
      identity: { ...caller, binding_generation: 7, window_instance_id: 'win-1' },
      command: 'CURRENT_NATIVE_BOOTSTRAP'
    }
  };
}

async function testExactIdentityAndCurrentNativeContract() {
  const h = makeHarness(validBootstrapResponse);
  const result = await h.request(h.tab);
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.bootstrap_contract.identity.conversation_key, 'fresh-key');

  const request = h.nativeMessages.find((message) => message.type === 'host:act' && message.op === 'bootstrap');
  assert.ok(request, 'bootstrap must use the native ACT bridge');
  assert.strictEqual(request.caller.conversation_key, 'fresh-key');
  assert.strictEqual(request.caller.tab_id, 7);
  assert.strictEqual(request.caller.transport_instance_id, 'instance1234');
}

async function testMissingConversationFailsBeforeNativeRequest() {
  const h = makeHarness(validBootstrapResponse);
  h.tab.url = 'https://chatgpt.com/';
  await assert.rejects(() => h.request(h.tab), /ACT_ENDPOINT_DRIFT/);
  assert.strictEqual(h.nativeMessages.filter((m) => m.type === 'host:act').length, 0);
}

async function testIdentityDriftFailsClosed() {
  const h = makeHarness((message) => {
    const response = validBootstrapResponse(message);
    response.bootstrap_contract.identity.conversation_key = 'other-key';
    return response;
  });
  await assert.rejects(() => h.request(h.tab), /ACT_BOOTSTRAP_IDENTITY_DRIFT/);
}

function testCurrentFileOwnershipAndContentHook() {
  const manifest = JSON.parse(fs.readFileSync('manifest.json', 'utf8'));
  assert.ok(!manifest.host_permissions.some((value) => /^http:\/\/127\.0\.0\.1:\d+/.test(value)));

  const bridge = fs.readFileSync('act_bridge.js', 'utf8');
  assert.ok(bridge.includes('async function requestActBootstrapResync(tab)'));
  assert.ok(bridge.includes("actNativeRequest('bootstrap', caller)"));

  const content = fs.readFileSync('content.js', 'utf8');
  assert.ok(content.includes("type:'relay:actBootstrapResync'") || content.includes("type: 'relay:actBootstrapResync'"));
}

(async () => {
  await testExactIdentityAndCurrentNativeContract();
  await testMissingConversationFailsBeforeNativeRequest();
  await testIdentityDriftFailsClosed();
  testCurrentFileOwnershipAndContentHook();
  console.log('ACT bootstrap hook tests: PASS (4/4 current native bridge)');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
