const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');

const local = {};
let createCount = 0;
let executeCount = 0;
let statusCount = 0;
const conversationKey = '6ad7f5b6-c834-83e8-9c00-ff70bab4204d';
const sha256 = async (value) => {
  const digest = await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(String(value)));
  return Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, '0')).join('');
};

const context = vm.createContext({
  console, crypto: webcrypto, TextEncoder, Uint8Array, setTimeout,
  endpointSessionReady: Promise.resolve(), endpointSessionId: 'session-1',
  NEW_CHAT_RECEIPTS_KEY: 'newChatReceiptsV1', relaySha256: sha256,
  stateRepository: {
    getLocal: async (key) => typeof key === 'string' ? { [key]: local[key] } : { ...local },
    setLocal: async (patch) => Object.assign(local, patch),
  },
  loadState: async () => ({ settings: { instanceId: 'instance123' } }),
  RelayCore: {
    conversationKey: (url) => String(url).match(/\/c\/([a-f0-9-]+)/i)?.[1] || '',
  },
  browserGateway: {
    getExactTab: async () => ({ id: 71, windowId: 11,
      url: `https://chatgpt.com/c/${conversationKey}` }),
    isChatTab: (tab) => /^https:\/\/chatgpt\.com\//.test(String(tab?.url || '')),
    sendWithReceiver: async (_tabId, message) => {
      if (message.type === 'relay:newChatExecute') {
        executeCount += 1;
        return { ok: true, submitted: true };
      }
      statusCount += 1;
      return { ok: true, submitted: true, completed: true,
        conversationKey, reply: 'NEW_CHAT_ACK' };
    },
  },
  getTabCreateAdapter: () => ({
    createTab: async (intent) => {
      createCount += 1;
      return { ok: true, state: 'PENDING_UNBOUND', tabId: 71, windowId: 11,
        sessionId: intent.sessionId };
    },
  }),
});
vm.runInContext(fs.readFileSync('domain/new_chat_service.js', 'utf8'), context,
  { filename: 'domain/new_chat_service.js' });

(async () => {
  const request = { operationId: 'new-chat-test-1', instanceId: 'instance123',
    windowId: 11, text: 'hello', responseTimeoutMs: 15000 };
  const first = await context.sendNewChatAndAwaitResult(request);
  assert.equal(first.ok, true);
  assert.equal(first.state, 'RESULT_PERSISTED');
  assert.equal(first.conversationKey, conversationKey);
  assert.equal(first.reply, 'NEW_CHAT_ACK');
  assert.equal(createCount, 1);
  assert.equal(executeCount, 1);
  assert.equal(statusCount, 1);

  const readback = context.publicPersistedNewChatResult({
    newChatReceipts: local.newChatReceiptsV1,
  }, request.operationId);
  assert.equal(readback.operationId, request.operationId);
  assert.equal(readback.state, 'RESULT_PERSISTED');
  assert.equal(readback.reply, 'NEW_CHAT_ACK');
  assert.equal(readback.replayed, true);
  assert.equal(context.publicPersistedNewChatResult({
    newChatReceipts: local.newChatReceiptsV1,
  }, 'missing-operation'), null);

  const duplicate = await context.sendNewChatAndAwaitResult(request);
  assert.equal(duplicate.ok, true);
  assert.equal(duplicate.replayed, true);
  assert.equal(createCount, 1);
  assert.equal(executeCount, 1);
  assert.equal(statusCount, 1);

  await assert.rejects(
    context.sendNewChatAndAwaitResult({ ...request, text: 'different' }),
    /NEW_CHAT_OPERATION_ID_REUSE_MISMATCH/,
  );

  const lateOperationId = 'new-chat-test-late-result';
  const lateTextSha256 = await sha256('late prompt');
  local.newChatReceiptsV1[lateOperationId] = {
    operationId: lateOperationId, command: 'new-chat-send',
    state: 'SUBMIT_UNKNOWN', instanceId: 'instance123', sessionId: 'session-1',
    tabId: 71, windowId: 11, conversationKey, textSha256: lateTextSha256,
    stageTiming: { beganAt: Date.now() },
  };
  const pendingStatus = context.publicPendingNewChatStatus(
    local.newChatReceiptsV1[lateOperationId],
  );
  assert.deepEqual(JSON.parse(JSON.stringify(pendingStatus)), {
    kind: 'NEW_CHAT', state: 'SUBMIT_UNKNOWN', tabId: 71, windowId: 11,
    requestedWindowId: null, conversationKey, textSha256: lateTextSha256,
    stageTiming: local.newChatReceiptsV1[lateOperationId].stageTiming, error: '',
  });
  const createsBeforeRecovery = createCount;
  const submissionsBeforeRecovery = executeCount;
  const statusesBeforeRecovery = statusCount;
  const recovered = await context.recoverPersistedNewChatResult({
    newChatReceipts: local.newChatReceiptsV1,
  }, lateOperationId);
  assert.equal(recovered.ok, true);
  assert.equal(recovered.state, 'RESULT_PERSISTED');
  assert.equal(recovered.reply, 'NEW_CHAT_ACK');
  assert.equal(createCount, createsBeforeRecovery);
  assert.equal(executeCount, submissionsBeforeRecovery);
  assert.equal(statusCount, statusesBeforeRecovery + 1);
  assert.equal(local.newChatReceiptsV1[lateOperationId].state, 'RESULT_PERSISTED');
  assert.equal(context.publicPendingNewChatStatus(
    local.newChatReceiptsV1[lateOperationId],
  ), null);

  local.newChatReceiptsV1['new-chat-test-pre-submit'] = {
    operationId: 'new-chat-test-pre-submit', state: 'CREATED',
    instanceId: 'instance123', sessionId: 'session-1', tabId: 71, windowId: 11,
    textSha256: lateTextSha256,
  };
  assert.equal(await context.recoverPersistedNewChatResult({
    newChatReceipts: local.newChatReceiptsV1,
  }, 'new-chat-test-pre-submit'), null);
  assert.equal(createCount, createsBeforeRecovery);
  assert.equal(executeCount, submissionsBeforeRecovery);
  console.log('rcc new chat service v1: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
