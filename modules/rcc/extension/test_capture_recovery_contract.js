const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { randomUUID, webcrypto } = require('crypto');

const source = fs.readFileSync('background.js', 'utf8') + `
  ;globalThis.__captureRecoveryTest = {
    handleNativeCommand,
    setNativePort(value) { nativePort = value; }
  };`;

const relayId = 'orch.send.live-capture-regression';
const role = 'BCT_ORCH_TEST_W1';
const conversationKey = 'conversation-capture-regression';
const tabId = 901;
const submittedText = 'one exact bounded assignment';
const persistedFailure = {
  routeId: relayId,
  to: role,
  resultState: 'RESULT_PERSISTED',
  resultPayload: {
    ok: false,
    reply: '',
    error: 'net::ERR_ABORTED',
    ambiguous: false,
    failureEvidence: {
      phase: 'FINAL_DOM_VALIDATION',
      networkError: 'net::ERR_ABORTED',
      domError: 'RELAY_FINAL_DOM_NOT_READY:ROUTE_TURN_NOT_RESOLVED',
      networkSignal: 'FAILED'
    }
  },
  dispatchFingerprint: JSON.stringify([role, submittedText]),
  tabId,
  conversationKey,
  createdAt: Date.now(),
  ackState: 'UNACKED',
  returnState: 'NOT_REQUESTED',
  receiverAckState: 'NOT_REQUESTED'
};
const store = {
  registrations: {
    [role]: { role, tabId, conversationKey, authorization: 'ACT_CONVERSATION_BIND' }
  },
  settings: { token: 'test-token', armed: true, budget: 1, instanceId: 'a'.repeat(32) },
  pending: {},
  results: [],
  processed: [],
  operations: {},
  relayResultReceiptsV1: { [relayId]: persistedFailure },
  bindingSubmitLeasesV1: {}
};
const posted = [];
const sentMessages = [];
let directRecoveryCalls = 0;
let directRecoveryResult = {
  ok: false, error: 'RELAY_RECOVERY_DIRECT_TURN_AMBIGUOUS'
};
const port = {
  onMessage: { addListener() {} },
  onDisconnect: { addListener() {} },
  postMessage(value) { posted.push(value); }
};
const tab = { id: tabId, url: `https://chatgpt.com/c/${conversationKey}`, title: 'Worker' };
const context = {
  console, URL, TextEncoder, Uint8Array,
  setTimeout, clearTimeout, setInterval: () => 0, clearInterval: () => {},
  crypto: { randomUUID, subtle: webcrypto.subtle },
  RelayCore: require('./relay_core.js'),
  chrome: {
    storage: {
      local: {
        get: async () => store,
        set: async (patch) => Object.assign(store, patch)
      }
    },
    tabs: {
      query: async () => [tab],
      get: async (id) => {
        assert.strictEqual(Number(id), tabId);
        return tab;
      },
      sendMessage: async (_id, message) => {
        sentMessages.push(message);
        return {
          ok: false,
          recovered: false,
          error: 'RELAY_RECOVERY_DOM_UNKNOWN:ROUTE_TURN_NOT_RESOLVED'
        };
      }
    },
    scripting: {
      executeScript: async (spec) => {
        if (Array.isArray(spec?.args)) {
          directRecoveryCalls += 1;
          return [{ result: directRecoveryResult }];
        }
        return [{ result: true }];
      }
    },
    runtime: {
      id: 'test-extension',
      onMessage: { addListener() {} },
      connectNative: () => port,
      onStartup: { addListener() {} },
      onInstalled: { addListener() {} }
    }
  }
};
vm.createContext(context);
vm.runInContext(source, context, { filename: 'background.js' });
context.__captureRecoveryTest.setNativePort(port);

(async () => {
  await context.__captureRecoveryTest.handleNativeCommand({
    type: 'host:command', command: 'recover-pending', requestId: 'recover-contract-test',
    to: role, text: relayId
  });
  const recoveryMessages = sentMessages.filter((item) => item.type === 'relay:recoverExecution');
  assert.strictEqual(recoveryMessages.length, 1,
    `content recovery is attempted once: ${JSON.stringify(posted)}`);
  assert.strictEqual(recoveryMessages[0].type, 'relay:recoverExecution');
  assert.strictEqual(directRecoveryCalls, 1, 'structured content failure must invoke direct recovery');
  const result = posted.find((item) => item.requestId === 'recover-contract-test');
  assert(result, 'native recovery result must be returned');
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.recovered, false, 'unchanged failure must not be advertised as recovered');
  assert.strictEqual(result.persistedResult, true);
  assert.strictEqual(result.resultUnchanged, true);
  assert.match(result.captureRecoveryError, /RELAY_RECOVERY_DIRECT_TURN_AMBIGUOUS/);
  assert.strictEqual(store.relayResultReceiptsV1[relayId], persistedFailure,
    'failed recovery must preserve the original durable receipt');

  const recoveredRelayId = `${relayId}-success`;
  store.relayResultReceiptsV1[recoveredRelayId] = {
    ...persistedFailure,
    routeId: recoveredRelayId
  };
  directRecoveryResult = {
    ok: true,
    reply: '[BCT_ORCHESTRATION_RESULT_V1]{"status":"SUCCEEDED"}[/BCT_ORCHESTRATION_RESULT_V1]'
  };
  await context.__captureRecoveryTest.handleNativeCommand({
    type: 'host:command', command: 'recover-pending', requestId: 'recover-contract-success',
    to: role, text: recoveredRelayId
  });
  assert.strictEqual(directRecoveryCalls, 2, 'successful case also performs one direct recovery');
  const recoveredResult = posted.find((item) => item.requestId === 'recover-contract-success');
  assert(recoveredResult, 'successful native recovery result must be returned');
  assert.strictEqual(recoveredResult.recovered, true);
  assert.strictEqual(store.relayResultReceiptsV1[recoveredRelayId].resultPayload.ok, true);
  assert.match(store.relayResultReceiptsV1[recoveredRelayId].resultPayload.reply, /SUCCEEDED/);
  console.log('capture recovery contract tests: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
