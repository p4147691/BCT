const assert = require('assert');
const path = require('path');

const root = __dirname;
const contract = require(path.join(root, 'browser/tab_close_contract.js'));
const adapterFactory = require(path.join(root, 'browser/tab_close_adapter.js'));

function harness(options = {}) {
  const calls = [];
  let removed = false;
  const liveTab = {
    id: 17, windowId: options.windowId || 5, index: 2,
    url: options.url || 'https://chatgpt.com/c/conversation-1234',
  };
  const chromeApi = {
    tabs: {
      get: async (tabId) => {
        calls.push(['get', tabId]);
        if (!removed && options.precheckError) throw new Error(options.precheckError);
        if (removed && options.afterTab) return { ...options.afterTab };
        if (removed && options.afterError) throw new Error(options.afterError);
        if (removed) throw new Error(`No tab with id: ${tabId}`);
        return { ...liveTab };
      },
      remove: async (tabId) => {
        calls.push(['remove', tabId]);
        removed = true;
        if (options.removeError) throw new Error(options.removeError);
      },
    },
  };
  const adapter = adapterFactory.create(chromeApi, contract, {
    isChatTab: (tab) => /^https:\/\/(chatgpt\.com|chat\.openai\.com)\//.test(String(tab?.url || '')),
    conversationKey: (url) => String(url).split('/c/')[1] || '',
  });
  return { adapter, calls };
}

const intent = {
  operationId: 'CLOSE-001', instanceId: 'instance-1', sessionId: 'session-1',
  tabId: 17, expectedWindowId: 5, conversationKey: 'conversation-1234',
};

(async () => {
  {
    const { adapter, calls } = harness();
    const receipt = await adapter.closeTab(intent);
    assert.equal(receipt.schema, contract.SCHEMA);
    assert.equal(receipt.state, 'CLOSED_CONFIRMED');
    assert.equal(receipt.effectState, 'APPLIED_CONFIRMED');
    assert.equal(receipt.closed, true);
    assert.equal(receipt.tabPresence, 'ABSENT');
    assert.equal(receipt.retrySafe, false);
    assert.deepEqual(calls, [['get', 17], ['remove', 17], ['get', 17]]);
  }
  {
    const { adapter, calls } = harness({ url: 'https://chatgpt.com/c/other-conversation' });
    const receipt = await adapter.closeTab(intent);
    assert.equal(receipt.state, 'NOT_APPLIED');
    assert.equal(receipt.effectState, 'NOT_APPLIED');
    assert.equal(calls.some(([name]) => name === 'remove'), false);
  }
  {
    const { adapter, calls } = harness({ windowId: 6 });
    const receipt = await adapter.closeTab(intent);
    assert.equal(receipt.state, 'NOT_APPLIED');
    assert.equal(calls.some(([name]) => name === 'remove'), false);
  }
  {
    const { adapter, calls } = harness({ precheckError: 'tab lookup failed' });
    const receipt = await adapter.closeTab(intent);
    assert.equal(receipt.state, 'NOT_APPLIED');
    assert.equal(calls.some(([name]) => name === 'remove'), false);
  }
  {
    const { adapter } = harness({ removeError: 'transport lost after invocation' });
    const receipt = await adapter.closeTab(intent);
    assert.equal(receipt.state, 'CLOSE_UNKNOWN');
    assert.equal(receipt.effectState, 'UNKNOWN');
    assert.equal(receipt.closed, false);
  }
  {
    const { adapter } = harness({ afterTab: {
      id: 17, windowId: 5, index: 2, url: 'https://chatgpt.com/c/conversation-1234',
    } });
    const receipt = await adapter.closeTab(intent);
    assert.equal(receipt.state, 'CLOSE_UNKNOWN');
    assert.equal(receipt.error, 'TAB_CLOSE_POSTCONDITION_UNPROVEN');
    assert.equal(receipt.after.tabId, 17);
  }
  {
    const { adapter } = harness({ afterError: 'browser transport unavailable' });
    const receipt = await adapter.closeTab(intent);
    assert.equal(receipt.state, 'CLOSE_UNKNOWN');
    assert.equal(receipt.error, 'browser transport unavailable');
  }
  assert.equal(contract.fingerprint(intent), contract.fingerprint({ ...intent }));
  assert.throws(() => contract.normalizeIntent({ ...intent, tabId: 0 }),
    /TAB_CLOSE_TAB_ID_INVALID/);
  assert.throws(() => contract.normalizeIntent({ ...intent, conversationKey: '?' }),
    /TAB_CLOSE_CONVERSATION_KEY_INVALID/);
  console.log('rcc browser tab close adapter v1: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
