const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');

const local = {};
let createCount = 0;
let executeCount = 0;
let moved = null;
let submitted = false;
const key = '6ad7f5b6-c834-83e8-9c00-ff70bab4204d';
const sha256 = async (value) => {
  const digest = await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(String(value)));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
};
const context = vm.createContext({
  console, crypto: webcrypto, TextEncoder, Uint8Array, setTimeout,
  endpointSessionReady: Promise.resolve(), endpointSessionId: 'session-1',
  NEW_CHAT_RECEIPTS_KEY: 'newChatReceiptsV1', relaySha256: sha256,
  stateRepository: {
    getLocal: async (name) => ({ [name]: local[name] }),
    setLocal: async (patch) => Object.assign(local, patch),
  },
  loadState: async () => ({ settings: { instanceId: 'instance-1' } }),
  RelayCore: { conversationKey: (url) => String(url).match(/\/c\/([a-f0-9-]+)/i)?.[1] || '' },
  browserGateway: {
    getExactTab: async () => ({ id: 71, windowId: 11,
      url: submitted ? `https://chatgpt.com/c/${key}` : 'https://chatgpt.com/' }),
    isChatTab: () => true,
    sendWithReceiver: async (_tabId, message) => {
      if (message.type === 'relay:newChatExecute') { executeCount += 1; submitted = true; return { ok: true, submitted: true }; }
      if (message.type === 'relay:newChatStatus') return { ok: true, submitted: true, completed: true, conversationKey: key, reply: 'ACK' };
      if (message.type === 'relay:retireExecution') return { ok: true, retired: true, relayId: message.relayId };
      throw new Error('unexpected receiver message');
    },
  },
  getTabCreateAdapter: () => ({ createTab: async (intent) => {
    createCount += 1;
    return { ok: true, state: 'PENDING_UNBOUND', tabId: 71, windowId: intent.requestedWindowId || 11,
      sessionId: intent.sessionId, creationReceipt: { operationId: intent.operationId } };
  } }),
  getWindowCreateAdapter: () => ({ createWindow: async (intent) => ({
    ok: true, state: 'PENDING_UNBOUND', tabId: 72, windowId: 12, sessionId: intent.sessionId,
  }) }),
  getTabMoveAdapter: () => ({ move: async (intent) => {
    moved = intent;
    return { ok: true, state: 'MOVED', effectState: 'APPLIED_CONFIRMED', tabId: intent.tabId,
      expectedWindowId: intent.expectedWindowId, targetWindowId: intent.targetWindowId };
  } }),
});
vm.runInContext(fs.readFileSync(`${__dirname}/domain/new_chat_service.js`, 'utf8'), context, { filename: 'new_chat_service.js' });
vm.runInContext(fs.readFileSync(`${__dirname}/domain/atomic_chat_service.js`, 'utf8'), context, { filename: 'atomic_chat_service.js' });

(async () => {
  const created = await context.createAtomicChatTab({ operationId: 'create-1', instanceId: 'instance-1', windowId: 11 });
  assert.equal(created.ok, true);
  assert.equal(created.sessionId, 'session-1');
  assert.equal(created.bindingState, 'PENDING_UNBOUND');
  const replayedCreate = await context.createAtomicChatTab({ operationId: 'create-1', instanceId: 'instance-1', windowId: 11 });
  assert.equal(replayedCreate.replayed, true);
  assert.equal(createCount, 1, 'a duplicate creation never opens another tab');

  const firstSend = await context.sendToAtomicCreatedTab({ operationId: 'send-1', createOperationId: 'create-1',
    instanceId: 'instance-1', sessionId: 'session-1', tabId: 71, windowId: 11, text: 'hello' });
  assert.equal(firstSend.ok, true);
  assert.equal(firstSend.command, 'send-to-created-tab');
  assert.equal(firstSend.id, 'send-1');
  assert.equal(firstSend.fingerprint, '["create-1","instance-1","session-1",71,11,"hello"]');
  assert.equal(executeCount, 1);
  const replayedSend = await context.sendToAtomicCreatedTab({ operationId: 'send-1', createOperationId: 'create-1',
    instanceId: 'instance-1', sessionId: 'session-1', tabId: 71, windowId: 11, text: 'hello' });
  assert.equal(replayedSend.replayed, true);
  assert.equal(executeCount, 1, 'a terminal first-send receipt is never resent');

  await assert.rejects(context.sendToAtomicCreatedTab({ operationId: 'bad-send', createOperationId: 'create-1',
    instanceId: 'instance-1', sessionId: 'wrong-session', tabId: 71, windowId: 11, text: 'hello' }), /ATOMIC_CHAT_SESSION_ID_MISMATCH/);

  const movedResult = await context.moveAtomicChatTab({ operationId: 'move-1', instanceId: 'instance-1', sessionId: 'session-1',
    tabId: 71, windowId: 11, targetWindowId: 12, index: -1, conversationKey: key });
  assert.equal(movedResult.state, 'MOVED');
  assert.equal(moved.targetWindowId, 12);
  console.log('rcc atomic chat service v1: PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });
