const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { randomUUID } = require('crypto');
const browserReadAdapter = require('./browser/read_adapter.js');
const legacyCommandPolicy = require('./legacy/command_policy.js');

const source = fs.readFileSync('background.js', 'utf8') +
  '\n;globalThis.__relayTest = { resolveRegistration, ensureRoleConversation };';

function conversationKey(url) {
  try {
    const match = new URL(url).pathname.match(/\/c\/([a-z0-9-]+)/i);
    return match ? match[1] : '';
  } catch {
    return '';
  }
}

function makeHarness(registrations, initialTabs, createDelayMs = 0) {
  let tabs = initialTabs.map((item) => ({ ...item }));
  let listener = null;
  const store = {
    registrations: JSON.parse(JSON.stringify(registrations)),
    settings: { token: 'test-token', armed: false, budget: 0, instanceId: 'testinstance1234' },
    pending: {}, results: [], processed: []
  };

  const port = {
    onMessage: { addListener() {} },
    onDisconnect: { addListener() {} },
    postMessage() {}
  };
  const context = {
    console, URL, setTimeout, clearTimeout, setInterval: () => 0, clearInterval: () => {},
    crypto: { randomUUID },
    RelayCore: {
      normalizeRole: (value) => String(value || '').trim().toUpperCase(),
      conversationKey,
      makeResultEnvelope: () => ''
    },
    RccBrowserReadAdapter: browserReadAdapter,
    RccLegacyCommandPolicy: legacyCommandPolicy,
    chrome: {
      storage: { local: {
        get: async () => store,
        set: async (patch) => Object.assign(store, patch)
      } },
      tabs: {
        query: async () => tabs,
        get: async (id) => {
          const tab = tabs.find((item) => item.id === Number(id));
          if (!tab) throw new Error('tab not found');
          return tab;
        },
        create: async ({ url, active }) => {
          const targetUrl = url;
          const tab = { id: 100 + tabs.length, url: createDelayMs ? 'about:blank' : url, title: '', active: !!active };
          tabs.push(tab);
          if (createDelayMs) setTimeout(() => { tab.url = targetUrl; }, createDelayMs);
          return tab;
        },
        sendMessage: async () => ({ ok: true })
      },
      scripting: { executeScript: async () => {} },
      runtime: {
        id: 'test-extension',
        onMessage: { addListener: (fn) => { listener = fn; } },
        connectNative: () => port,
        onStartup: { addListener() {} },
        onInstalled: { addListener() {} }
      }
    }
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: 'background.js' });

  async function hello(tab) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('hello timeout')), 1000);
      listener(
        { type: 'relay:hello', url: tab.url },
        { tab },
        (value) => { clearTimeout(timer); resolve(value); }
      );
    });
  }

  return {
    store,
    hello,
    resolveRegistration: context.__relayTest.resolveRegistration,
    ensureRoleConversation: context.__relayTest.ensureRoleConversation,
    setTabs(next) { tabs = next.map((item) => ({ ...item })); }
  };
}

async function testHelloDoesNotFollowTabDrift() {
  const h = makeHarness(
    { SOURCE: { role: 'SOURCE', tabId: 1, conversationKey: 'original' } },
    [{ id: 1, url: 'https://chatgpt.com/c/drifted', title: 'Drifted' }]
  );
  const reply = await h.hello({ id: 1, url: 'https://chatgpt.com/c/drifted' });
  assert.strictEqual(reply.ok, false);
  assert.match(reply.error, /RCC_RUNTIME_MESSAGE_LEGACY_MUTATION_DISABLED:relay:hello/);
  assert.strictEqual(h.store.registrations.SOURCE.conversationKey, 'original');
  assert.strictEqual(h.store.registrations.SOURCE.tabId, 1);
}
async function testHelloDoesNotRebindOriginalConversationOnNewTab() {
  const h = makeHarness(
    { SOURCE: { role: 'SOURCE', tabId: 1, conversationKey: 'original' } },
    [{ id: 2, url: 'https://chatgpt.com/c/original', title: 'Original' }]
  );
  const reply = await h.hello({ id: 2, url: 'https://chatgpt.com/c/original' });
  assert.strictEqual(reply.ok, false);
  assert.match(reply.error, /RCC_RUNTIME_MESSAGE_LEGACY_MUTATION_DISABLED:relay:hello/);
  assert.strictEqual(h.store.registrations.SOURCE.conversationKey, 'original');
  assert.strictEqual(h.store.registrations.SOURCE.tabId, 1);
}

async function testResolveRegistrationRebindsOriginalElsewhere() {
  const h = makeHarness(
    { SOURCE: { role: 'SOURCE', tabId: 1, conversationKey: 'original', title: 'Old' } },
    [
      { id: 1, url: 'https://chatgpt.com/c/drifted', title: 'Drifted' },
      { id: 2, url: 'https://chatgpt.com/c/original', title: 'Original' }
    ]
  );
  const reg = await h.resolveRegistration('SOURCE');
  assert.strictEqual(reg.tabId, 2);
  assert.strictEqual(reg.conversationKey, 'original');
}

async function testResolveRegistrationFailsClosedWhenOriginalMissing() {
  const h = makeHarness(
    { SOURCE: { role: 'SOURCE', tabId: 1, conversationKey: 'original' } },
    [{ id: 1, url: 'https://chatgpt.com/c/drifted', title: 'Drifted' }]
  );
  await assert.rejects(
    () => h.resolveRegistration('SOURCE'),
    /Registered tab is not open: SOURCE/
  );
  assert.strictEqual(h.store.registrations.SOURCE.conversationKey, 'original');
}

async function testEnsureOpensAndBindsMissingConversation() {
  const h = makeHarness(
    { SOURCE: { role: 'SOURCE', tabId: 1, conversationKey: 'wrong-key' } },
    []
  );
  const reg = await h.ensureRoleConversation('SOURCE', 'original');
  assert.strictEqual(reg.conversationKey, 'original');
  assert.strictEqual(reg.tabId, 100);
  assert.strictEqual(h.store.registrations.SOURCE.conversationKey, 'original');
}

async function testEnsureWaitsForCreatedConversationNavigation() {
  const h = makeHarness(
    { SOURCE: { role: 'SOURCE', tabId: 1, conversationKey: 'wrong-key' } },
    [],
    80
  );
  const reg = await h.ensureRoleConversation('SOURCE', 'delayed-original');
  assert.strictEqual(reg.conversationKey, 'delayed-original');
  assert.strictEqual(reg.tabId, 100);
}

(async () => {
  await testHelloDoesNotFollowTabDrift();
  await testHelloDoesNotRebindOriginalConversationOnNewTab();
  await testResolveRegistrationRebindsOriginalElsewhere();
  await testResolveRegistrationFailsClosedWhenOriginalMissing();
  await testEnsureOpensAndBindsMissingConversation();
  await testEnsureWaitsForCreatedConversationNavigation();
  console.log('identity guard tests: PASS (6/6)');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
