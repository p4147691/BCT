const assert = require('assert');
const path = require('path');

const root = __dirname;
const contract = require(path.join(root, 'browser/window_create_contract.js'));
const adapterFactory = require(path.join(root, 'browser/window_create_adapter.js'));

function harness(options = {}) {
  const calls = [];
  const tab = {
    id: 61, windowId: 31, index: 0,
    url: options.tabUrl || 'https://chatgpt.com/',
  };
  const chromeApi = {
    windows: {
      create: async (createOptions) => {
        calls.push(['window-create', createOptions]);
        if (options.createError) throw new Error(options.createError);
        const created = { id: options.missingWindowId ? null : 31, state: 'normal' };
        if (!options.omitEmbeddedTab) created.tabs = [{ ...tab }];
        return created;
      },
      get: async (windowId) => {
        calls.push(['window-get', windowId]);
        if (options.windowGetError) throw new Error(options.windowGetError);
        return { id: options.wrongWindowId || windowId, state: 'normal' };
      },
    },
    tabs: {
      query: async (query) => {
        calls.push(['tab-query', query]);
        return options.emptyQuery ? [] : [{ ...tab }];
      },
      get: async (tabId) => {
        calls.push(['tab-get', tabId]);
        if (options.tabGetError) throw new Error(options.tabGetError);
        return { ...tab };
      },
    },
  };
  const adapter = adapterFactory.create(chromeApi, contract, {
    isChatTab: (value) => /^https:\/\/(chatgpt\.com|chat\.openai\.com)\//.test(String(value?.url || '')),
    conversationKey: (url) => String(url).split('/c/')[1] || '',
  }, { readyTimeoutMs: 0, pollIntervalMs: 0 });
  return { adapter, calls };
}

const intent = {
  operationId: 'WINDOW-CREATE-001', instanceId: 'instance-1', sessionId: 'session-1',
  conversationKey: '',
};

(async () => {
  {
    const { adapter, calls } = harness();
    const receipt = await adapter.createWindow(intent);
    assert.equal(receipt.schema, contract.SCHEMA);
    assert.equal(receipt.state, 'PENDING_UNBOUND');
    assert.equal(receipt.effectState, 'APPLIED_CONFIRMED');
    assert.equal(receipt.retrySafe, false);
    assert.equal(receipt.windowId, 31);
    assert.equal(receipt.tabId, 61);
    assert.equal(receipt.windowState, 'NORMAL');
    assert.equal(receipt.tabPresence, 'OPEN');
    assert.equal(receipt.creationReceipt.bindingState, 'PENDING_UNBOUND');
    assert.deepEqual(calls[0], ['window-create', {
      url: 'https://chatgpt.com/', type: 'normal', focused: true,
    }]);
  }
  {
    const { adapter, calls } = harness({ omitEmbeddedTab: true });
    const receipt = await adapter.createWindow({ ...intent, operationId: 'WINDOW-CREATE-002' });
    assert.equal(receipt.state, 'PENDING_UNBOUND');
    assert.equal(calls.some(([name]) => name === 'tab-query'), true);
  }
  {
    const { adapter } = harness({ createError: 'transport lost' });
    const receipt = await adapter.createWindow(intent);
    assert.equal(receipt.state, 'CREATE_UNKNOWN');
    assert.equal(receipt.effectState, 'UNKNOWN');
    assert.equal(receipt.created, false);
    assert.equal(receipt.error, 'CREATE_UNKNOWN');
  }
  {
    const { adapter } = harness({ missingWindowId: true });
    const receipt = await adapter.createWindow(intent);
    assert.equal(receipt.state, 'CREATE_UNKNOWN');
    assert.equal(receipt.windowId, null);
  }
  {
    const { adapter } = harness({ tabUrl: 'https://chatgpt.com/c/conversation-1234' });
    const receipt = await adapter.createWindow(intent);
    assert.equal(receipt.state, 'CREATE_UNKNOWN');
    assert.equal(receipt.tabPresence, 'UNKNOWN');
  }
  {
    const { adapter } = harness({ windowGetError: 'window lookup failed' });
    const receipt = await adapter.createWindow(intent);
    assert.equal(receipt.state, 'CREATE_UNKNOWN');
  }
  assert.equal(contract.fingerprint(intent), contract.fingerprint({ ...intent }));
  assert.throws(() => contract.normalizeIntent({ ...intent, conversationKey: 'conversation-1234' }),
    /WINDOW_CREATE_CONVERSATION_KEY_FORBIDDEN/);
  console.log('rcc browser window create adapter v1: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
