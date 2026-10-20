const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { randomUUID, webcrypto } = require('crypto');

const source = fs.readFileSync('background.js', 'utf8') + `
  ;globalThis.__captureRecoveryTest = {
    handleNativeCommand
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
  RccLegacyCommandPolicy: require('./legacy/command_policy.js'),
  RccChromeStateRepository: require('./platform/chrome_state_repository.js'),
  RccBrowserGateway: require('./platform/browser_gateway.js'),
  RccNativeTransport: require('./platform/native_transport.js'),
  RccObservationGateway: require('./platform/observation_gateway.js'),
  RccLifecycle: require('./platform/lifecycle.js'),
  chrome: {
    storage: {
      local: {
        get: async () => store,
        set: async (patch) => Object.assign(store, patch)
      },
      session: {
        get: async () => ({}),
        set: async () => {}
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

(async () => {
  const before = JSON.stringify(store.relayResultReceiptsV1);
  await context.__captureRecoveryTest.handleNativeCommand({
    type: 'host:command', command: 'recover-pending', requestId: 'recover-contract-test',
    to: role, text: relayId
  });
  const rejected = posted.find((item) => item.requestId === 'recover-contract-test');
  assert(rejected, 'legacy recovery rejection must return a receipt');
  assert.strictEqual(rejected.ok, false);
  assert.strictEqual(rejected.effectState, 'NOT_APPLIED');
  assert.match(rejected.error, /RCC_NATIVE_COMMAND_LEGACY_MUTATION_DISABLED:recover-pending/);
  assert.strictEqual(sentMessages.length, 0, 'disabled recovery must not contact a chat tab');
  assert.strictEqual(directRecoveryCalls, 0, 'disabled recovery must not invoke direct DOM recovery');
  assert.strictEqual(JSON.stringify(store.relayResultReceiptsV1), before,
    'disabled recovery must preserve historical receipts unchanged');
  console.log('capture recovery contract tests: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
