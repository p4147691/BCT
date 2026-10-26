const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = __dirname;
const browserReadAdapter = require(path.join(root, 'browser/read_adapter.js'));
const calls = [];
const chromeApi = {
  tabs: {
    query: async (query) => {
      calls.push(['query', query]);
      return [
        { id: 1, windowId: 2, index: 3, url: 'https://chatgpt.com/c/abc', title: 'ChatGPT' },
        { id: 3, windowId: 4, url: 'https://example.test/', title: 'Other' },
      ];
    },
    sendMessage: async (tabId, message) => {
      calls.push(['probe', tabId, message]);
      return { generating: false };
    },
  },
  windows: { get: async (windowId) => ({ id: windowId, focused: true }) },
};

const adapter = browserReadAdapter.create(chromeApi, ['https://chatgpt.com/*']);
(async () => {
  const tabs = await adapter.queryChatTabs();
  assert.deepEqual(tabs.map((tab) => tab.id), [1]);
  assert.deepEqual(calls[0], ['query', { url: ['https://chatgpt.com/*'] }]);
  assert.equal(adapter.isChatTab(tabs[0]), true);
  assert.equal(adapter.isChatTab({ url: 'https://example.test/' }), false);
  assert.deepEqual(adapter.publicTab(tabs[0]), {
    tabId: 1, windowId: 2, index: 3, title: 'ChatGPT', url: 'https://chatgpt.com/c/abc',
  });
  assert.deepEqual(await adapter.getWindow(2), { id: 2, focused: true });
  assert.deepEqual(await adapter.probeActivity(1), { generating: false });
  assert.deepEqual(calls[1], ['probe', 1, { type: 'relay:activityProbe' }]);
  assert.throws(() => browserReadAdapter.create(null, ['https://chatgpt.com/*']),
    /RCC_BROWSER_READ_ADAPTER_CHROME_API_REQUIRED/);
  assert.throws(() => browserReadAdapter.create(chromeApi, []),
    /RCC_BROWSER_READ_ADAPTER_CHAT_URLS_REQUIRED/);

  const source = fs.readFileSync(path.join(root, 'browser/read_adapter.js'), 'utf8');
  for (const prohibited of ['tabs.create', 'tabs.move', 'tabs.remove', 'tabs.reload', 'windows.create', 'windows.update']) {
    assert(!source.includes(prohibited), `read adapter must not contain ${prohibited}`);
  }
  console.log('rcc browser read adapter v1: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
