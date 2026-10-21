const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = __dirname;
const source = fs.readFileSync(path.join(root, 'domain/orchestration_relay_service.js'), 'utf8');
const contentSource = fs.readFileSync(path.join(root, 'content/orchestration_relay_executor.js'), 'utf8');
const loader = fs.readFileSync(path.join(root, 'background_loader.js'), 'utf8');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));

function harness() {
  const conversationKey = '6ad7f5b6-c834-83e8-9c00-ff70bab4204d';
  const expected = {
    instanceId: 'instance-1', sessionId: 'session-1', tabId: 42,
    conversationKey, bindingReceiptId: 'RCB-ABCDEF1234567890', attachmentGeneration: 3,
  };
  const state = {
    settings: { instanceId: expected.instanceId }, pending: {}, resultReceipts: {},
    registrations: { BB_MGR: {
      role: 'BB_MGR', tabId: expected.tabId, conversationKey,
      transportInstanceId: expected.instanceId, sessionId: expected.sessionId,
      bindingReceiptId: expected.bindingReceiptId,
    } },
  };
  const sent = [];
  const context = vm.createContext({
    console, endpointSessionReady: Promise.resolve(), endpointSessionId: expected.sessionId,
    RELAY_RESULT_RECEIPTS_KEY: 'relayResultReceiptsV1',
    loadState: async () => state,
    stateRepository: {
      setLocal: async (patch) => {
        if (patch.pending) state.pending = patch.pending;
        if (patch.relayResultReceiptsV1) state.resultReceipts = patch.relayResultReceiptsV1;
      },
      getLocal: async () => ({ relayResultReceiptsV1: state.resultReceipts }),
    },
    browserGateway: { getExactTab: async (tabId) => ({ id: Number(tabId),
      url: `https://chatgpt.com/c/${conversationKey}` }) },
    isChatTab: (tab) => String(tab?.url || '').startsWith('https://chatgpt.com/'),
    RelayCore: { normalizeRole: (value) => String(value || '').trim().toUpperCase(),
      conversationKey: (url) => /\/c\/([^/?#]+)/.exec(url)?.[1] || '' },
    publicResultFromReceipt: (receipt) => receipt ? {
      id: receipt.routeId, fingerprint: receipt.dispatchFingerprint,
      reply: receipt.resultPayload?.reply || '',
    } : null,
    sendToChatTab: async (tabId, message) => {
      sent.push({ tabId, message });
      return { ok: true, submitted: true, bindingAttestation: { ...expected } };
    },
    relaySha256: async (value) => `hash-${String(value).length}`,
    lifecycle: { runtimeSenderKind: (sender) => sender?.id === 'extension-1'
      ? 'CHAT_CONTENT' : 'UNTRUSTED' },
    Date, JSON, Number, Object, String, Promise, Error, RegExp, Map,
  });
  vm.runInContext(source, context, { filename: 'orchestration_relay_service.js' });
  return { context, state, sent, expected, conversationKey };
}

(async () => {
  const h = harness();
  const message = {
    to: 'bb_mgr', text: 'hello', messageHash: 'a'.repeat(64), fromNode: 'BCT_MANAGER',
    expectedInstanceId: h.expected.instanceId, expectedSessionId: h.expected.sessionId,
    expectedTabId: h.expected.tabId, expectedConversationKey: h.expected.conversationKey,
    bindingReceiptId: h.expected.bindingReceiptId,
    attachmentGeneration: h.expected.attachmentGeneration,
  };
  const first = await h.context.sendOrchestrationRelay(message, 'orch.send.1');
  assert.equal(first.ok, true);
  assert.equal(first.submitted, true);
  assert.equal(h.sent.length, 1);
  assert.equal(h.state.pending['orch.send.1'].deliveryConfirmed, true);

  const replay = await h.context.sendOrchestrationRelay(message, 'orch.send.1');
  assert.equal(replay.duplicate, true);
  assert.equal(replay.pending, true);
  assert.equal(h.sent.length, 1, 'a pending operation must not submit twice');

  const sender = { id: 'extension-1', frameId: 0,
    tab: { id: 42, url: `https://chatgpt.com/c/${h.conversationKey}` } };
  const authorized = await h.context.authorizeOrchestrationRelay({
    relayId: 'orch.send.1', exactBinding: { ...h.expected },
  }, sender);
  assert.equal(authorized.authorized, true);

  const stored = await h.context.persistOrchestrationRelayResult({
    relayId: 'orch.send.1', bindingAttestation: { ...h.expected },
    result: { ok: true, reply: 'done' },
  }, sender);
  assert.equal(stored.ok, true);
  assert.equal(h.state.pending['orch.send.1'], undefined);
  assert.equal(h.state.resultReceipts['orch.send.1'].resultState, 'RESULT_PERSISTED');

  const completed = await h.context.sendOrchestrationRelay(message, 'orch.send.1');
  assert.equal(completed.completed, true);
  assert.equal(h.sent.length, 1, 'a completed operation must not submit twice');

  const second = await h.context.sendOrchestrationRelay(message, 'orch.send.2');
  assert.equal(second.submitted, true);
  h.context.endpointSessionId = 'reloaded-session';
  await assert.rejects(
    h.context.persistOrchestrationRelayResult({
      relayId: 'orch.send.2', bindingAttestation: { ...h.expected },
      result: { ok: true, reply: 'stale result' },
    }, sender),
    /ORCHESTRATION_RELAY_RESULT_BINDING_MISMATCH/,
  );
  h.context.endpointSessionId = h.expected.sessionId;

  await assert.rejects(
    h.context.sendOrchestrationRelay({ ...message, expectedSessionId: 'stale' }, 'orch.send.2'),
    /ORCHESTRATION_RELAY_SESSION_MISMATCH/,
  );
  assert(loader.includes("importScripts('domain/orchestration_relay_service.js');"));
  assert(manifest.content_scripts[0].js.includes('content/orchestration_relay_executor.js'));
  assert(contentSource.includes("authorizeOrchestrationContent(message, 'PRE_SUBMIT')"));
  assert(contentSource.includes('waitForExactUserSubmission(record, 8000)'));
  console.log('orchestration relay v1: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
