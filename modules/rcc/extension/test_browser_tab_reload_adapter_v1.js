const assert = require('assert');
const path = require('path');

const root = __dirname;
const contract = require(path.join(root, 'browser/tab_reload_contract.js'));
const adapterFactory = require(path.join(root, 'browser/tab_reload_adapter.js'));

function harness(options = {}) {
  const calls = [];
  const listeners = new Set();
  let reloaded = false;
  const tab = {
    id: 29, windowId: 7, index: 3,
    url: options.url || 'https://chatgpt.com/c/conversation-1234',
  };
  const chromeApi = {
    tabs: {
      get: async (tabId) => {
        calls.push(['get', tabId]);
        if (!reloaded && options.precheckError) throw new Error(options.precheckError);
        if (reloaded && options.afterError) throw new Error(options.afterError);
        return { ...tab, url: reloaded && options.afterUrl ? options.afterUrl : tab.url };
      },
      reload: async (tabId) => {
        calls.push(['reload', tabId]);
        reloaded = true;
        if (options.reloadError) throw new Error(options.reloadError);
        if (!options.noCompleteEvent) {
          for (const listener of [...listeners]) listener(tabId, { status: 'complete' }, { ...tab });
        }
      },
      onUpdated: {
        addListener: (listener) => listeners.add(listener),
        removeListener: (listener) => listeners.delete(listener),
      },
    },
  };
  const adapter = adapterFactory.create(chromeApi, contract, {
    isChatTab: (value) => /^https:\/\/(chatgpt\.com|chat\.openai\.com)\//.test(String(value?.url || '')),
    conversationKey: (url) => String(url).split('/c/')[1] || '',
  }, {
    probe: async (tabId) => {
      calls.push(['probe', tabId]);
      if (options.probeError) throw new Error(options.probeError);
      return { ok: options.probeOk !== false };
    },
  }, { navigationTimeoutMs: 0, receiverTimeoutMs: 0, pollIntervalMs: 0 });
  return { adapter, calls, listeners };
}

const intent = {
  operationId: 'RELOAD-001', instanceId: 'instance-1', sessionId: 'session-1',
  targetRole: 'WORKER', tabId: 29, conversationKey: 'conversation-1234',
};

(async () => {
  {
    const { adapter, calls, listeners } = harness();
    const receipt = await adapter.reloadTab(intent);
    assert.equal(receipt.schema, contract.SCHEMA);
    assert.equal(receipt.state, 'RELOADED_CONFIRMED');
    assert.equal(receipt.effectState, 'APPLIED_CONFIRMED');
    assert.equal(receipt.reloaded, true);
    assert.equal(receipt.navigationCompleted, true);
    assert.equal(receipt.receiverReady, true);
    assert.equal(receipt.retrySafe, false);
    assert.deepEqual(calls, [['get', 29], ['reload', 29], ['get', 29], ['probe', 29]]);
    assert.equal(listeners.size, 0);
  }
  {
    const { adapter, calls } = harness({ url: 'https://chatgpt.com/c/other-conversation' });
    const receipt = await adapter.reloadTab(intent);
    assert.equal(receipt.state, 'NOT_APPLIED');
    assert.equal(receipt.effectState, 'NOT_APPLIED');
    assert.equal(calls.some(([name]) => name === 'reload'), false);
  }
  {
    const { adapter, calls } = harness({ precheckError: 'tab missing' });
    const receipt = await adapter.reloadTab(intent);
    assert.equal(receipt.state, 'NOT_APPLIED');
    assert.equal(calls.some(([name]) => name === 'reload'), false);
  }
  {
    const { adapter, listeners } = harness({ reloadError: 'transport lost' });
    const receipt = await adapter.reloadTab(intent);
    assert.equal(receipt.state, 'RELOAD_UNKNOWN');
    assert.equal(receipt.effectState, 'UNKNOWN');
    assert.equal(listeners.size, 0);
  }
  {
    const { adapter } = harness({ noCompleteEvent: true });
    const receipt = await adapter.reloadTab(intent);
    assert.equal(receipt.state, 'RELOAD_UNKNOWN');
    assert.equal(receipt.error, 'TAB_RELOAD_NAVIGATION_UNPROVEN');
  }
  {
    const { adapter } = harness({ probeOk: false });
    const receipt = await adapter.reloadTab(intent);
    assert.equal(receipt.state, 'RELOAD_UNKNOWN');
    assert.equal(receipt.navigationCompleted, true);
    assert.equal(receipt.receiverReady, false);
  }
  {
    const { adapter } = harness({ afterUrl: 'https://chatgpt.com/c/changed-conversation' });
    const receipt = await adapter.reloadTab(intent);
    assert.equal(receipt.state, 'RELOAD_UNKNOWN');
  }
  assert.equal(contract.fingerprint(intent), contract.fingerprint({ ...intent }));
  assert.throws(() => contract.normalizeIntent({ ...intent, conversationKey: '?' }),
    /TAB_RELOAD_CONVERSATION_KEY_INVALID/);
  console.log('rcc browser tab reload adapter v1: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
