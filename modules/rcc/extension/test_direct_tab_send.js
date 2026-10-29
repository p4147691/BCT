const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');

const instanceId = '6174664e1c1b4e6db1d4729c841db3c9';
const sessionId = '786b7b6b9671446f85497e097111e5ec';
const conversationKey = '6ad4bb5d-6624-83ee-b045-e57fdad5120e';
const tabs = new Map([
  [41, { id: 41, windowId: 9, index: 4, url: 'https://chatgpt.com/', title: 'ChatGPT' }],
  [42, { id: 42, windowId: 9, index: 0, url: `https://chatgpt.com/c/${conversationKey}`, title: 'History' }],
  [43, { id: 43, windowId: 9, index: 5, url: 'https://chatgpt.com/', title: 'ChatGPT' }],
  [44, { id: 44, windowId: 9, index: 6, url: 'https://chatgpt.com/', title: 'ChatGPT' }],
  [45, { id: 45, windowId: 9, index: 7, url: 'https://chatgpt.com/', title: 'ChatGPT' }],
]);
const local = {};
const sends = [];
// Virtual clock: a slow provider must not make a successful first send UNKNOWN.
const clock = { elapsed: 0 };
class TestDate extends Date { static now() { return clock.elapsed; } }
const fakeSetTimeout = (fn, ms) => { clock.elapsed += ms; Promise.resolve().then(fn); };
const sha256 = async (value) => {
  const digest = await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(String(value)));
  return Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, '0')).join('');
};
const context = vm.createContext({
  crypto: webcrypto, TextEncoder, Uint8Array, setTimeout: fakeSetTimeout, Date: TestDate, console,
  endpointSessionReady: Promise.resolve(), endpointSessionId: sessionId,
  EXACT_TAB_SEND_RECEIPTS_KEY: 'exactTabSendReceiptsV1', relaySha256: sha256,
  stateRepository: {
    getLocal: async (key) => ({ [key]: local[key] }),
    setLocal: async (patch) => Object.assign(local, patch),
  },
  loadState: async () => ({ settings: { instanceId } }),
  RelayCore: {
    conversationKey: (url) => String(url).match(/\/c\/([a-f0-9-]{36})/i)?.[1] || '',
  },
  browserGateway: {
    getExactTab: async (tabId) => {
      const tab = tabs.get(Number(tabId));
      if (!tab) throw new Error('TAB_NOT_FOUND');
      return { ...tab };
    },
    isChatTab: (tab) => /^https:\/\/chatgpt\.com\//.test(String(tab?.url || '')),
    sendWithReceiver: async (tabId, message) => {
      sends.push({ tabId, message });
      if (message.type === 'relay:newChatExecute' && tabId === 43) {
        tabs.get(43).url = `https://chatgpt.com/c/${conversationKey}`;
        return { ok: false, submitted: false, effectState: 'UNKNOWN',
          error: 'CONVERSATION_IDENTITY_CHANGED' };
      }
      if (message.type === 'relay:newChatExecute' && [44, 45].includes(tabId)) {
        tabs.get(tabId).url = `https://chatgpt.com/c/${conversationKey}`;
        return { ok: false, submitted: false, effectState: 'UNKNOWN',
          error: 'CONVERSATION_IDENTITY_CHANGED' };
      }
      if (message.type === 'relay:newChatStatus' && tabId === 44) {
        return clock.elapsed < 14000
          ? { ok: true, submitted: false, conversationKey }
          : { ok: true, submitted: true, relayId: message.relayId, conversationKey };
      }
      if (message.type === 'relay:newChatStatus' && tabId === 45) {
        return { ok: true, submitted: false, conversationKey };
      }
      if (message.type === 'relay:newChatStatus' && tabId === 43) {
        return { ok: true, submitted: true, relayId: message.relayId, conversationKey };
      }
      if (message.type === 'relay:newChatExecute') {
        return { ok: true, submitted: true, relayId: message.relayId, conversationKey: '' };
      }
      return { ok: true, submitted: true, relayId: message.relayId, conversationKey };
    },
  },
});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'domain/exact_tab_send_service.js'), 'utf8'), context,
  { filename: 'domain/exact_tab_send_service.js' });

const request = (operationId, tabId, key = '', windowId = 9) => ({
  operationId, instanceId, sessionId, workId: 'bounded-work', tabId, windowId,
  conversationKey: key, text: 'bounded prompt',
});

(async () => {
  const blank = await context.sendToExactExistingTab(request('direct-blank', 41));
  assert.equal(blank.ok, true);
  assert.equal(blank.state, 'SUBMITTED');
  assert.equal(blank.tabId, 41);
  assert.equal(sends.length, 1);
  assert.equal(sends[0].message.type, 'relay:newChatExecute');

  const replay = await context.sendToExactExistingTab(request('direct-blank', 41));
  assert.equal(replay.ok, true);
  assert.equal(replay.replayed, true);
  assert.equal(sends.length, 1, 'same operation must never submit twice');

  // Index is deliberately irrelevant: tab 42 was moved to index 0 before this call.
  const existing = await context.sendToExactExistingTab(
    request('direct-existing', 42, conversationKey),
  );
  assert.equal(existing.ok, true);
  assert.equal(existing.state, 'SUBMITTED');
  assert.equal(sends.length, 2);
  assert.equal(sends[1].tabId, 42);
  assert.equal(sends[1].message.type, 'relay:simpleExecute');

  // Move the same tab to another Chrome window.  Its tabId and UUID still
  // identify it; the caller's old windowId is only contextual information.
  tabs.get(42).windowId = 10;
  const movedWindow = await context.sendToExactExistingTab(
    request('direct-moved-window', 42, conversationKey, 9),
  );
  assert.equal(movedWindow.state, 'SUBMITTED');
  assert.equal(movedWindow.windowId, 10);
  assert.equal(sends.length, 3);

  // A blank-tab receiver can lose its first response while ChatGPT replaces
  // the route.  Recover from the same tab and its exact persisted turn; do
  // not send the prompt a second time.
  const recoveredBlank = await context.sendToExactExistingTab(
    request('direct-blank-status-recovery', 43),
  );
  assert.equal(recoveredBlank.state, 'SUBMITTED');
  assert.equal(recoveredBlank.conversationKey, conversationKey);
  assert.equal(sends.filter((item) => item.tabId === 43
    && item.message.type === 'relay:newChatExecute').length, 1);
  assert.equal(sends.filter((item) => item.tabId === 43
    && item.message.type === 'relay:newChatStatus').length, 1);

  // Recovery beyond the old 12 s bound: still one Execute and exact proof.
  const delayed = await context.sendToExactExistingTab(request('direct-delayed-receipt', 44));
  assert.equal(delayed.state, 'SUBMITTED');
  assert.equal(delayed.conversationKey, conversationKey);
  assert.equal(sends.filter(item => item.tabId === 44 && item.message.type === 'relay:newChatExecute').length, 1);
  assert.ok(sends.filter(item => item.tabId === 44 && item.message.type === 'relay:newChatStatus').length > 60);

  // Never convert an unproven submission into APPLIED, even after 25 s.
  const unresolved = await context.sendToExactExistingTab(request('direct-unproven-receipt', 45));
  assert.equal(unresolved.state, 'UNKNOWN');
  assert.equal(unresolved.submitted, false);
  assert.equal(sends.filter(item => item.tabId === 45 && item.message.type === 'relay:newChatExecute').length, 1);

  const beforeWrongSessionSendCount = sends.length;
  await assert.rejects(
    context.sendToExactExistingTab({ ...request('direct-wrong-session', 42, conversationKey), sessionId: 'f'.repeat(32) }),
    /EXACT_TAB_SESSION_MISMATCH/,
  );
  assert.equal(sends.length, beforeWrongSessionSendCount);
  console.log('RCC_DIRECT_TAB_TEST_PASS cases=8 sends=' + sends.length);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
