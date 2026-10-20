const assert = require('assert');
const path = require('path');

const root = __dirname;
const contract = require(path.join(root, 'browser/tab_create_contract.js'));
const adapterFactory = require(path.join(root, 'browser/tab_create_adapter.js'));

function harness(options = {}) {
  const calls = [];
  let createdTab = null;
  const chromeApi = {
    windows: {
      get: async (windowId) => {
        calls.push(['window-get', windowId]);
        if (options.windowError) throw new Error(options.windowError);
        return { id: options.wrongWindowId || windowId };
      },
    },
    tabs: {
      create: async (createOptions) => {
        calls.push(['create', createOptions]);
        if (options.createError) throw new Error(options.createError);
        createdTab = { id: 41, windowId: createOptions.windowId || 7, index: 2,
          url: options.createdUrl || createOptions.url };
        return { ...createdTab };
      },
      get: async (tabId) => {
        calls.push(['tab-get', tabId]);
        if (options.getError) throw new Error(options.getError);
        return { ...createdTab };
      },
    },
  };
  const adapter = adapterFactory.create(chromeApi, contract, {
    isChatTab: (tab) => /^https:\/\/(chatgpt\.com|chat\.openai\.com)\//.test(String(tab?.url || '')),
    conversationKey: (url) => String(url).split('/c/')[1] || '',
  }, { readyTimeoutMs: 0, pollIntervalMs: 0 });
  return { adapter, calls };
}

const blankIntent = {
  operationId: 'CREATE-001', instanceId: 'instance-1', sessionId: 'session-1',
  requestedWindowId: 7, conversationKey: '',
};

(async () => {
  {
    const { adapter, calls } = harness();
    const receipt = await adapter.createTab(blankIntent);
    assert.equal(receipt.schema, contract.SCHEMA);
    assert.equal(receipt.state, 'PENDING_UNBOUND');
    assert.equal(receipt.effectState, 'APPLIED_CONFIRMED');
    assert.equal(receipt.retrySafe, false);
    assert.equal(receipt.creationReceipt.bindingState, 'PENDING_UNBOUND');
    assert.equal(receipt.creationReceipt.tabId, 41);
    assert.deepEqual(calls[1], ['create', {
      url: 'https://chatgpt.com/', active: false, windowId: 7,
    }]);
  }
  {
    const { adapter, calls } = harness({ windowError: 'window missing' });
    const receipt = await adapter.createTab(blankIntent);
    assert.equal(receipt.state, 'NOT_APPLIED');
    assert.equal(receipt.effectState, 'NOT_APPLIED');
    assert.equal(calls.some(([name]) => name === 'create'), false);
  }
  {
    const { adapter } = harness({ createError: 'transport lost' });
    const receipt = await adapter.createTab(blankIntent);
    assert.equal(receipt.state, 'CREATE_UNKNOWN');
    assert.equal(receipt.effectState, 'UNKNOWN');
    assert.equal(receipt.retrySafe, false);
  }
  {
    const { adapter } = harness({ createdUrl: 'https://example.test/' });
    const receipt = await adapter.createTab(blankIntent);
    assert.equal(receipt.state, 'CREATE_UNKNOWN');
    assert.equal(receipt.error, 'TAB_CREATE_POSTCONDITION_UNPROVEN');
    assert.equal(receipt.created, true);
  }
  {
    const { adapter, calls } = harness();
    const receipt = await adapter.createTab({
      ...blankIntent, operationId: 'CREATE-002', requestedWindowId: null,
      conversationKey: 'conversation-1234',
    });
    assert.equal(receipt.state, 'CREATED_CONFIRMED');
    assert.equal(receipt.conversationKey, 'conversation-1234');
    assert.deepEqual(calls[0], ['create', {
      url: 'https://chatgpt.com/c/conversation-1234', active: false,
    }]);
  }
  assert.equal(contract.fingerprint(blankIntent), contract.fingerprint({ ...blankIntent }));
  assert.throws(() => contract.normalizeIntent({ ...blankIntent, requestedWindowId: -1 }),
    /TAB_CREATE_WINDOW_ID_INVALID/);
  console.log('rcc browser tab create adapter v1: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
