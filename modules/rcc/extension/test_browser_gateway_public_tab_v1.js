const assert = require('assert');
const path = require('path');

const gatewayModule = require(path.join(__dirname, 'platform/browser_gateway.js'));
const chromeApi = {
  tabs: {
    query: async () => [],
    sendMessage: async () => ({ ok: true }),
    get: async () => { throw new Error('unused'); },
  },
  scripting: { executeScript: async () => [{ result: true }] },
  windows: { get: async () => ({ id: 2 }) },
};

const gateway = gatewayModule.create(chromeApi, {
  chatUrls: ['https://chatgpt.com/*'], receiverFiles: ['content.js'],
});
const publicTab = gateway.publicTab({
  id: 1, windowId: 2, index: 3, title: 'ChatGPT', url: 'https://chatgpt.com/c/example',
});

assert.deepEqual(publicTab, {
  tabId: 1, windowId: 2, index: 3, title: 'ChatGPT', url: 'https://chatgpt.com/c/example',
});
assert.equal(Object.hasOwn(publicTab, 'id'), false,
  'the RCC public state must not leak the raw Chrome field spelling');

console.log('rcc browser gateway public tab v1: PASS');
