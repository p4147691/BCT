const assert = require('assert');
const path = require('path');

const root = __dirname;
const contract = require(path.join(root, 'browser/tab_move_contract.js'));
const adapterFactory = require(path.join(root, 'browser/tab_move_adapter.js'));

function harness(options = {}) {
  const calls = [];
  let tab = { id: 17, windowId: 3, index: 1, url: 'https://chatgpt.com/c/abc-12345' };
  const chromeApi = { tabs: {
    get: async (tabId) => {
      calls.push(['get', tabId]);
      return { ...tab };
    },
    query: async (query) => {
      calls.push(['query', query]);
      return options.targetTabs || [{ ...tab }, { id: 18, windowId: query.windowId, index: 0 }];
    },
    move: async (tabId, target) => {
      calls.push(['move', tabId, target]);
      if (options.moveError) throw new Error(options.moveError);
      tab = { ...tab, windowId: options.wrongPostWindow || target.windowId,
        index: target.index === -1 ? 1 : target.index };
      return { ...tab };
    },
  } };
  const adapter = adapterFactory.create(chromeApi, contract, {
    isChatTab: (value) => /^https:\/\/chatgpt\.com\//.test(String(value?.url || '')),
    conversationKey: (url) => String(url).split('/c/')[1] || '',
  });
  return { adapter, calls, setTab: (value) => { tab = value; } };
}

const intent = {
  operationId: 'MOVE-001', tabId: 17, expectedWindowId: 3,
  targetWindowId: 9, requestedIndex: 0, conversationKey: 'abc-12345',
};

(async () => {
  {
    const { adapter, calls } = harness();
    const receipt = await adapter.move(intent);
    assert.equal(receipt.schema, contract.SCHEMA);
    assert.equal(receipt.state, 'MOVED');
    assert.equal(receipt.effectState, 'APPLIED_CONFIRMED');
    assert.equal(receipt.retrySafe, false);
    assert.deepEqual(receipt.before, { tabId: 17, windowId: 3, index: 1 });
    assert.deepEqual(receipt.after, { tabId: 17, windowId: 9, index: 0 });
    assert.deepEqual(calls[2], ['move', 17, { windowId: 9, index: 0 }]);
  }
  {
    const { adapter, calls, setTab } = harness();
    setTab({ id: 17, windowId: 4, index: 1, url: 'https://chatgpt.com/c/abc-12345' });
    const receipt = await adapter.move(intent);
    assert.equal(receipt.state, 'NOT_APPLIED');
    assert.equal(receipt.effectState, 'NOT_APPLIED');
    assert.equal(receipt.error, 'TAB_MOVE_SOURCE_IDENTITY_MISMATCH');
    assert.equal(calls.some(([name]) => name === 'move'), false);
  }
  {
    const { adapter } = harness({ moveError: 'transport lost' });
    const receipt = await adapter.move(intent);
    assert.equal(receipt.state, 'MOVE_UNKNOWN');
    assert.equal(receipt.effectState, 'UNKNOWN');
    assert.equal(receipt.retrySafe, false);
  }
  {
    const { adapter } = harness({ wrongPostWindow: 8 });
    const receipt = await adapter.move(intent);
    assert.equal(receipt.state, 'MOVE_UNKNOWN');
    assert.equal(receipt.error, 'TAB_MOVE_POSTCONDITION_UNPROVEN');
  }
  assert.equal(contract.fingerprint(intent), contract.fingerprint({ ...intent }));
  assert.throws(() => contract.normalizeIntent({ ...intent, requestedIndex: -2 }),
    /TAB_MOVE_INDEX_INVALID/);
  console.log('rcc browser tab move adapter v1: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
