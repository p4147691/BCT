const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/domain/conversation_rename_service.js`, 'utf8');
const conversationKey = '6ad75568-a1b2-c3d4-e5f6-123456789012';
const tab = { id: 42, windowId: 7, url: `https://chatgpt.com/c/${conversationKey}`, title: 'old' };

function createHarness(reply = { ok: true, operationId: 'rename-op-1', savedTitle: 'new' }) {
  const local = { renameReceiptsV1: {} };
  const sent = [];
  const context = vm.createContext({
    console,
    endpointSessionReady: Promise.resolve(),
    endpointSessionId: 'session-1',
    RENAME_RECEIPTS_KEY: 'renameReceiptsV1',
    loadState: async () => ({ renameReceipts: { ...local.renameReceiptsV1 } }),
    stateRepository: { setLocal: async (patch) => Object.assign(local, patch) },
    browserGateway: { getExactTab: async (tabId) => {
      if (tabId !== 42) throw new Error('missing');
      return { ...tab };
    } },
    isChatTab: (value) => String(value?.url || '').startsWith('https://chatgpt.com/'),
    RelayCore: { conversationKey: (url) => /\/c\/([^/?#]+)/.exec(url)?.[1] || '' },
    sendToChatTab: async (tabId, message) => { sent.push({ tabId, message }); return reply; },
    publishEndpointSnapshot: async () => [],
    Date,
    JSON,
    Number,
    String,
    Promise,
    Error,
  });
  vm.runInContext(source, context, { filename: 'conversation_rename_service.js' });
  return { context, local, sent };
}

(async () => {
  const harness = createHarness();
  const request = {
    operationId: 'rename-op-1', conversationKey, tabId: 42,
    sessionId: 'session-1', title: 'new',
  };
  const first = await harness.context.renameConversation(request, 'request-1');
  assert.equal(first.ok, true);
  assert.equal(first.state, 'APPLIED');
  assert.equal(first.savedTitle, 'new');
  assert.equal(harness.sent.length, 1);
  assert.equal(harness.local.renameReceiptsV1['rename-op-1'].terminal, true);

  const replay = await harness.context.renameConversation(request, 'request-1');
  assert.equal(replay.ok, true);
  assert.equal(replay.replayed, true);
  assert.equal(harness.sent.length, 1, 'terminal replay must not repeat UI effect');

  const conflict = await harness.context.renameConversation({ ...request, title: 'other' }, 'request-1');
  assert.equal(conflict.ok, false);
  assert.equal(conflict.state, 'NOT_APPLIED');
  assert.equal(conflict.error, 'RENAME_OPERATION_ID_REUSE_MISMATCH');

  const failedHarness = createHarness({
    ok: false, effectState: 'NOT_APPLIED', error: 'RENAME_ACTION_NOT_FOUND',
  });
  const failed = await failedHarness.context.renameConversation(request, 'request-1');
  assert.equal(failed.state, 'NOT_APPLIED');
  assert.equal(failed.ambiguous, false);
  assert.equal(failedHarness.local.renameReceiptsV1['rename-op-1'].terminal, true);

  const unknownHarness = createHarness({
    ok: false, effectState: 'UNKNOWN', error: 'RENAME_UI_NOT_VERIFIED',
  });
  const unknown = await unknownHarness.context.renameConversation(request, 'request-1');
  assert.equal(unknown.state, 'UNKNOWN');
  assert.equal(unknown.ambiguous, true);
  assert.equal(unknownHarness.local.renameReceiptsV1['rename-op-1'].terminal, false);

  console.log('conversation rename service v1: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
