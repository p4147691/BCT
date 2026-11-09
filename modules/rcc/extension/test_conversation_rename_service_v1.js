const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/domain/conversation_rename_service.js`, 'utf8');
const conversationKey = '6ad75568-a1b2-c3d4-e5f6-123456789012';
const dotKey = 'b227a510-d0cb-4466-a2f5-4e401b456dca~6af1261141a8819aa57d94044451fee3';
const tab = { id: 42, windowId: 7, url: `https://chatgpt.com/c/${conversationKey}`, title: 'old' };

function createHarness(reply = { ok: true, operationId: 'rename-op-1', savedTitle: 'new' }, exactTab = tab) {
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
      return { ...exactTab };
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
    URL,
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

  const dotHarness = createHarness(
    { ok: true, operationId: 'dot-rename-op-1', savedTitle: 'new dot' },
    { ...tab, url: `https://chatgpt.com/dots/${dotKey}` },
  );
  const dotRequest = {
    operationId: 'dot-rename-op-1', dotKey, tabId: 42,
    sessionId: 'session-1', title: 'new dot',
  };
  const dotResult = await dotHarness.context.renameDot(dotRequest, 'dot-request-1');
  assert.equal(dotResult.ok, true);
  assert.equal(dotResult.dotKey, dotKey);
  assert.equal(dotHarness.sent[0].message.type, 'relay:renameDot');
  assert.equal(dotHarness.sent[0].message.dotKey, dotKey);
  assert.equal(dotHarness.sent[0].message.conversationKey, undefined);
  const dotReplay = await dotHarness.context.renameDot(dotRequest, 'dot-request-1');
  assert.equal(dotReplay.replayed, true);
  assert.equal(dotHarness.sent.length, 1, 'Dot terminal replay must not repeat UI effect');

  const dotNoopHarness = createHarness(
    { ok: false, effectState: 'UNKNOWN', error: 'must-not-dispatch' },
    { ...tab, url: `https://chatgpt.com/dots/${dotKey}`, title: 'same dot - ChatGPT' },
  );
  const dotNoopRequest = {
    operationId: 'dot-noop-op-1', dotKey, tabId: 42,
    sessionId: 'session-1', title: 'same dot',
  };
  const dotNoop = await dotNoopHarness.context.renameDot(dotNoopRequest, 'dot-noop-request-1');
  assert.equal(dotNoop.ok, true);
  assert.equal(dotNoop.noUiEffect, true);
  assert.equal(dotNoopHarness.sent.length, 0, 'same-title Dot rename must not open the UI');

  const dotUnknownHarness = createHarness(
    { ok: false, effectState: 'UNKNOWN', error: 'DOT_RENAME_UI_NOT_VERIFIED' },
    { ...tab, url: `https://chatgpt.com/dots/${dotKey}`, title: 'old dot' },
  );
  const dotUnknownRequest = {
    operationId: 'dot-unknown-op-1', dotKey, tabId: 42,
    sessionId: 'session-1', title: 'resolved dot',
  };
  const dotUnknown = await dotUnknownHarness.context.renameDot(
    dotUnknownRequest, 'dot-unknown-request-1'
  );
  assert.equal(dotUnknown.state, 'UNKNOWN');
  assert.equal(dotUnknownHarness.sent.length, 1);
  dotUnknownHarness.context.browserGateway.getExactTab = async () => ({
    ...tab, url: `https://chatgpt.com/dots/${dotKey}`, title: 'resolved dot',
  });
  const dotReconciled = await dotUnknownHarness.context.renameDot(
    dotUnknownRequest, 'dot-unknown-request-1'
  );
  assert.equal(dotReconciled.ok, true);
  assert.equal(dotReconciled.reconciled, true);
  assert.equal(dotUnknownHarness.sent.length, 1, 'reconciliation must not repeat the UI effect');
  assert.equal(dotUnknownHarness.local.renameReceiptsV1['dot-unknown-op-1'].terminal, true);

  const mismatchedDot = createHarness(
    { ok: true, operationId: 'dot-rename-op-2', savedTitle: 'wrong' },
    { ...tab, url: `https://chatgpt.com/dots/other~context` },
  );
  const mismatch = await mismatchedDot.context.renameDot({
    ...dotRequest, operationId: 'dot-rename-op-2', title: 'wrong',
  }, 'dot-request-2');
  assert.equal(mismatch.ok, false);
  assert.equal(mismatch.error, 'DOT_RENAME_TAB_IDENTITY_MISMATCH');
  assert.equal(mismatchedDot.sent.length, 0);

  console.log('conversation rename service v1: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
