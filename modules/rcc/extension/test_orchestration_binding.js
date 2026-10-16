const fs = require('fs');
const vm = require('vm');
const { webcrypto } = require('crypto');
const resultHashFixture = JSON.parse(
  fs.readFileSync('fixtures/result_hash_v1.json', 'utf8')
);

const noopEvent = { addListener() {}, removeListener() {} };
const nativePort = {
  onMessage: noopEvent,
  onDisconnect: noopEvent,
  postMessage() {},
};
const liveTabs = new Map();
const chrome = {
  runtime: {
    id: 'ocbidbaplechjjdacmokhnfbdmgjkphf',
    onInstalled: noopEvent,
    onMessage: noopEvent,
    onStartup: noopEvent,
    connectNative() { return nativePort; },
    reload() {},
  },
  storage: {
    session: { async get() { return {}; }, async set() {} },
    local: { async get() { return {}; }, async set() {} },
  },
  tabs: {
    onCreated: noopEvent, onRemoved: noopEvent, onUpdated: noopEvent,
    async query() { return Array.from(liveTabs.values()); },
    async get(tabId) { return liveTabs.get(Number(tabId)) || null; },
    async create() {}, async move() {}, async reload() {}, async remove() {},
    async sendMessage() { return { ok: true, submitted: true }; },
  },
  windows: { async create() {}, async get() { return null; } },
  scripting: { async executeScript() {} },
  webRequest: {
    onBeforeRequest: noopEvent, onCompleted: noopEvent, onErrorOccurred: noopEvent,
  },
};
const context = vm.createContext({
  chrome, crypto: webcrypto, URL, console, process, liveTabs, resultHashFixture,
  setTimeout() { return 1; }, clearTimeout() {},
  TextEncoder, TextDecoder,
});
vm.runInContext(fs.readFileSync('relay_core.js', 'utf8'), context);
const background = fs.readFileSync('background.js', 'utf8');
const tests = String.raw`
;(async () => {
  await endpointSessionReady;
  if (resultHashFixture.schema !== 1) {
    throw new Error('unsupported result hash fixture schema');
  }
  for (const vector of resultHashFixture.vectors) {
    const serialized = JSON.stringify(boundedRelayResultPayload(vector.input));
    const digest = await relaySha256(serialized);
    if (serialized !== vector.bounded_json || digest !== vector.sha256) {
      throw new Error('result hash fixture mismatch: ' + vector.name);
    }
  }
  endpointSessionId = 'session123';
  const baseRegistration = {
    role: 'BCT_W1', bindingReceiptId: 'RCB-AAAAAAAAAAAA',
    transportInstanceId: 'instance123', sessionId: 'session123',
    tabId: 201, conversationKey: 'conversation-b',
    authorization: 'ACT_CONVERSATION_BIND'
  };
  const makeState = () => ({
    registrations: { BCT_W1: { ...baseRegistration } },
    settings: { instanceId: 'instance123' }, pending: {}, results: [],
    processed: [], operations: {}, resultReceipts: {}, bindingSubmitLeases: {}
  });
  let state = makeState();
  let sends = 0;
  let sentMessage = null;
  resolveRegistration = async () => ({ ...state.registrations.BCT_W1 });
  loadState = async () => state;
  sendToChatTab = async (_tabId, message) => {
    sends += 1;
    sentMessage = message;
    const sender = { id: chrome.runtime.id, frameId: 0,
      tab: { id: 201, url: 'https://chatgpt.com/c/conversation-b' } };
    const authorization = await authorizeInjectionSender(
      sender, 'conversation-b', message.exactBinding, message.relayId, 'PRE_SUBMIT'
    );
    if (!authorization.authorized || !authorization.bindingAttestation?.leaseId) {
      throw new Error('pre-submit lease was not issued');
    }
    const consumed = await consumeBindingSubmitLease(
      sender, message.relayId, authorization.bindingAttestation
    );
    return { ok: true, submitted: true,
      bindingAttestation: consumed.bindingAttestation };
  };
  const exact = {
    to: 'BCT_W1', text: 'bounded task', id: 'relay-ok', source: 'test',
    messageHash: 'digest-1', targetBindingReceipt: 'RCB-AAAAAAAAAAAA',
    expectedInstanceId: 'instance123', expectedSessionId: 'session123',
    expectedTabId: 201, expectedConversationKey: 'conversation-b',
    attachmentGeneration: 3, returnToControl: false, returnToRole: ''
  };

  await dispatchRelay(exact);
  if (sends !== 1) throw new Error('exact dispatch did not submit once');
  if (!sentMessage?.exactBinding
      || sentMessage.exactBinding.sessionId !== 'session123'
      || sentMessage.exactBinding.bindingReceiptId !== 'RCB-AAAAAAAAAAAA'
      || sentMessage.exactBinding.attachmentGeneration !== 3) {
    throw new Error('relay:execute did not carry the exact binding tuple');
  }

  const sender = { id: chrome.runtime.id, frameId: 0,
    tab: { id: 201, url: 'https://chatgpt.com/c/conversation-b' } };
  const authorized = await authorizeInjectionSender(
    sender, 'conversation-b', sentMessage.exactBinding, 'relay-ok'
  );
  if (authorized.authorized !== true
      || !orchestrationBindingAttestationMatches(
        sentMessage.exactBinding, authorized.bindingAttestation
      )) throw new Error('content authorization did not attest the exact pending binding');

  state.registrations.BCT_W1.sessionId = 'session456';
  endpointSessionId = 'session456';
  const staleAuthorization = await authorizeInjectionSender(
    sender, 'conversation-b', sentMessage.exactBinding, 'relay-ok'
  );
  if (staleAuthorization.authorized !== false) {
    throw new Error('session rebind was not fenced at content authorization time');
  }
  state.registrations.BCT_W1.sessionId = 'session123';
  endpointSessionId = 'session123';

  const dispatchedState = state;
  state = makeState();
  state.pending['relay-interleave'] = {
    to: 'BCT_W1', tabId: 201, conversationKey: 'conversation-b',
    expectedInstanceId: 'instance123', expectedSessionId: 'session123',
    targetBindingReceipt: 'RCB-AAAAAAAAAAAA', attachmentGeneration: 3
  };
  const exactBindingForTest = {
    instanceId: 'instance123', sessionId: 'session123', tabId: 201,
    conversationKey: 'conversation-b', bindingReceiptId: 'RCB-AAAAAAAAAAAA',
    attachmentGeneration: 3
  };
  const leaseAuthorization = await authorizeInjectionSender(
    sender, 'conversation-b', exactBindingForTest,
    'relay-interleave', 'PRE_SUBMIT'
  );
  if (!leaseAuthorization.authorized || !leaseAuthorization.bindingAttestation?.leaseId) {
    throw new Error('final authorization did not issue an exact lease');
  }
  let leaseFence = '';
  try {
    await mutateRegistrationsWithLeaseFence([{ role: 'BCT_W1' }], async (latest) => {
      latest.registrations.BCT_W1.sessionId = 'session456';
    });
  } catch (error) { leaseFence = String(error.message || error); }
  if (leaseFence !== 'PRE_SUBMIT_BINDING_LEASE_ACTIVE'
      || state.registrations.BCT_W1.sessionId !== 'session123') {
    throw new Error('registration mutation interleaved through the live lease');
  }
  liveTabs.set(202, { id: 202, title: 'relocated',
    url: 'https://chatgpt.com/c/conversation-b' });
  let relocationFence = '';
  try { await registerRole('BCT_W1', 202); }
  catch (error) { relocationFence = String(error.message || error); }
  if (relocationFence !== 'PRE_SUBMIT_BINDING_LEASE_ACTIVE'
      || Number(state.registrations.BCT_W1.tabId) !== 201) {
    throw new Error('role relocation interleaved through the live lease');
  }
  let reconnectFence = '';
  try { await reconcileRegistrationsWithTabs([liveTabs.get(202)]); }
  catch (error) { reconnectFence = String(error.message || error); }
  if (reconnectFence !== 'PRE_SUBMIT_BINDING_LEASE_ACTIVE'
      || Number(state.registrations.BCT_W1.tabId) !== 201) {
    throw new Error('session/tab rebind interleaved through the live lease');
  }
  const consumedLease = await consumeBindingSubmitLease(
    sender, 'relay-interleave', leaseAuthorization.bindingAttestation
  );
  if (!consumedLease.bindingAttestation?.leaseConsumedAt
      || state.bindingSubmitLeases[leaseAuthorization.bindingAttestation.leaseId]) {
    throw new Error('lease was not atomically consumed into the pending attestation');
  }
  const replayAuthorization = await authorizeInjectionSender(
    sender, 'conversation-b', exactBindingForTest,
    'relay-interleave', 'PRE_SUBMIT'
  );
  if (replayAuthorization.authorized !== false
      || replayAuthorization.reason !== 'RCC_PRE_SUBMIT_LEASE_ALREADY_CONSUMED') {
    throw new Error('consumed lease authorized a duplicate submit');
  }
  await mutateRegistrationsWithLeaseFence([{ role: 'BCT_W1' }], async (latest) => {
    latest.registrations.BCT_W1.sessionId = 'session456';
  });
  if (state.registrations.BCT_W1.sessionId !== 'session456') {
    throw new Error('registration mutation remained blocked after lease consumption');
  }
  state.registrations.BCT_W1.sessionId = 'session123';

  state.bindingSubmitLeases['RCL-EXPIRED'] = {
    ...exactBindingForTest, leaseId: 'RCL-EXPIRED', relayId: 'relay-expired',
    role: 'BCT_W1', expiresAt: Date.now() - 1
  };
  await expireBindingSubmitLease('RCL-EXPIRED');
  if (state.bindingSubmitLeases['RCL-EXPIRED']) throw new Error('expired lease was not removed');
  state = dispatchedState;

  let mismatch = '';
  try { await dispatchRelay({ ...exact, id: 'relay-bad', targetBindingReceipt: 'RCB-BBBBBBBBBBBB' }); }
  catch (error) { mismatch = String(error.message || error); }
  if (mismatch !== 'TARGET_BINDING_RECEIPT_MISMATCH' || sends !== 1) {
    throw new Error('binding receipt mismatch was not fenced before submit');
  }

  let duplicate = '';
  try { await dispatchRelay({ ...exact, messageHash: 'digest-2' }); }
  catch (error) { duplicate = String(error.message || error); }
  if (duplicate !== 'RELAY_ID_REUSE_MISMATCH' || sends !== 1) {
    throw new Error('changed duplicate fingerprint was not fenced: ' + duplicate + ':' + sends);
  }

  state = makeState();
  let reads = 0;
  loadState = async () => {
    reads += 1;
    if (reads === 2) state.registrations.BCT_W1.bindingReceiptId = 'RCB-CCCCCCCCCCCC';
    return state;
  };
  mismatch = '';
  try { await dispatchRelay({ ...exact, id: 'relay-race' }); }
  catch (error) { mismatch = String(error.message || error); }
  if (mismatch !== 'TARGET_BINDING_CHANGED_BEFORE_SUBMIT' || sends !== 1) {
    throw new Error('pre-submit rebind race was not fenced');
  }

  state = makeState();
  loadState = async () => state;
  sendToChatTab = async () => ({ ok: false, submitted: false,
    effectState: 'NOT_APPLIED', error: 'RCC_PRE_SUBMIT_LEASE_CONFLICT' });
  const notApplied = await dispatchRelay({ ...exact, id: 'relay-not-applied' });
  if (notApplied.effectState !== 'NOT_APPLIED' || state.pending['relay-not-applied']) {
    throw new Error('confirmed pre-submit failure was not released as NOT_APPLIED');
  }

  state = makeState();
  sendToChatTab = async () => ({ ok: false, submitted: false,
    error: 'LEGACY_RESULT_WITHOUT_EFFECT_STATE' });
  const unknown = await dispatchRelay({ ...exact, id: 'relay-unknown' });
  if (unknown.effectState !== 'UNKNOWN'
      || state.pending['relay-unknown']?.submitUnknown !== true) {
    throw new Error('unclassified post-dispatch failure was not quarantined as UNKNOWN');
  }

  console.log('4 orchestration binding fences PASS; 3 content authorization fences PASS; 7 lease interleaving fences PASS; 2 dispatch outcome fences PASS; result hash fixture PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });

`;
vm.runInContext(background + tests, context);

const content = fs.readFileSync('content.js', 'utf8');
const matchStart = content.indexOf('function exactBindingAttestationMatches(');
const matchEnd = content.indexOf('async function relayChatInjectionAuthorization(', matchStart);
if (matchStart < 0 || matchEnd <= matchStart) throw new Error('content exact-binding helper missing');
const matchContext = vm.createContext({ result: null });
vm.runInContext(content.slice(matchStart, matchEnd)
  + ';result=exactBindingAttestationMatches;', matchContext);
const expected = {
  instanceId: 'instance123', sessionId: 'session123', tabId: 201,
  conversationKey: 'conversation-b', bindingReceiptId: 'RCB-AAAAAAAAAAAA',
  attachmentGeneration: 3,
};
if (!matchContext.result(expected, { ...expected })
    || matchContext.result(expected, { ...expected, sessionId: 'session456' })) {
  throw new Error('content exact-binding tuple comparison failed');
}

const authorizationEnd = content.indexOf('let relayRole = null;', matchStart);
if (authorizationEnd <= matchStart) throw new Error('content authorization helpers missing');
const routeLocation = { pathname: '/c/conversation-b' };
const routeContext = vm.createContext({
  result: null, location: routeLocation,
  chrome: { runtime: { async sendMessage() {
    routeLocation.pathname = '/c/conversation-c';
    return { ok: true, authorized: true, conversationKey: 'conversation-b',
      bindingAttestation: { ...expected } };
  } } },
});
vm.runInContext(content.slice(matchStart, authorizationEnd)
  + ';result=relayChatInjectionAuthorization;', routeContext);
(async () => {
  const authorization = await routeContext.result(expected, 'relay-route-change', 'PRE_SUBMIT');
  if (authorization !== null) throw new Error('location change during authorization was not fenced');
  console.log('1 content post-authorization location fence PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });

const executeStart = content.indexOf('async function executeRelayMessage(');
const executeEnd = content.indexOf('async function deliverToControl(', executeStart);
if (executeStart < 0 || executeEnd <= executeStart) {
  throw new Error('content executeRelayMessage helper missing');
}
function executeContextForPhase(phase) {
  let draft = 'bounded task';
  let cleared = 0;
  const record = { relayId: 'relay-outcome', phase, submittedText: 'bounded task' };
  const ctx = vm.createContext({
    result: null,
    beginRelayExecution: async () => { throw new Error('SUBMIT_PATH_FAILED'); },
    loadRelayExecution: () => record,
    getEditor: () => ({}),
    editorDraftText: () => draft,
    setEditorText: (_editor, value) => { draft = String(value); },
    clearRelayExecution: () => { cleared += 1; },
    RelayCore: { normalizeMessageText: (value) => String(value).trim() },
  });
  vm.runInContext(content.slice(executeStart, executeEnd)
    + ';result=executeRelayMessage;', ctx);
  return { ctx, get cleared() { return cleared; }, get draft() { return draft; } };
}
(async () => {
  const before = executeContextForPhase('submit-intent');
  const notApplied = await before.ctx.result({ relayId: 'relay-outcome' });
  if (notApplied.effectState !== 'NOT_APPLIED' || before.cleared !== 1 || before.draft !== '') {
    throw new Error('pre-activation failure did not clear the exact draft as NOT_APPLIED');
  }
  const after = executeContextForPhase('submit-attempted');
  const unknown = await after.ctx.result({ relayId: 'relay-outcome' });
  if (unknown.effectState !== 'UNKNOWN' || after.cleared !== 0 || after.draft !== 'bounded task') {
    throw new Error('post-activation failure did not preserve evidence as UNKNOWN');
  }
  console.log('2 content submission outcome fences PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });

const beginStart = content.indexOf('async function beginRelayExecution(');
const beginEnd = content.indexOf('async function executeRelayMessage(', beginStart);
if (beginStart < 0 || beginEnd <= beginStart) {
  throw new Error('content beginRelayExecution helper missing');
}
let queuedRelays = 0;
let staleResultRecoveries = 0;
const completedPrior = {
  relayId: 'bootstrap-completed', phase: 'completed',
  result: { ok: true, reply: '{"ready":true}' }
};
const staleDrainContext = vm.createContext({
  result: null,
  RelayCore: { normalizeMessageText: (value) => String(value).trim() },
  requireExactRelayAuthorization: async (_message) => ({ ...expected }),
  relayChatInjectionEnabled: async () => true,
  connectionProblem: () => ({ disconnected: false }),
  loadRelayExecution: () => completedPrior,
  retirePersistedRelayExecution: async () => false,
  deferRelayExecution: () => {
    queuedRelays += 1;
    return { ok: true, deferred: true, replayed: false, queueDepth: 1 };
  },
  recoverRelayExecutionAfterReload: () => {
    staleResultRecoveries += 1;
    return Promise.resolve();
  },
});
vm.runInContext(content.slice(beginStart, beginEnd)
  + ';result=beginRelayExecution;', staleDrainContext);
(async () => {
  const deferred = await staleDrainContext.result({
    relayId: 'next-assignment', text: 'bounded task', exactBinding: expected
  });
  if (deferred.effectState !== 'NOT_APPLIED' || deferred.submitted !== false
      || queuedRelays !== 0 || staleResultRecoveries !== 1) {
    throw new Error('completed stale result did not recover then fail exact dispatch closed');
  }
  console.log('1 completed-result exact-dispatch recovery fence PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });

const deferStart = content.indexOf('function deferRelayExecution(');
const deferEnd = content.indexOf('async function drainDeferredRelayQueue(', deferStart);
if (deferStart < 0 || deferEnd <= deferStart) {
  throw new Error('content deferRelayExecution helper missing');
}
let deferredItems = [];
const deferredBindingContext = vm.createContext({
  result: null,
  loadDeferredRelayQueue: () => deferredItems,
  saveDeferredRelayQueue: (items) => { deferredItems = items; },
  scheduleDeferredRelayDrain() {},
});
vm.runInContext(content.slice(deferStart, deferEnd)
  + ';result=deferRelayExecution;', deferredBindingContext);
const queuedBinding = {
  instanceId: 'instance123', sessionId: 'session123', tabId: 201,
  conversationKey: 'conversation-b', bindingReceiptId: 'RCB-AAAAAAAAAAAA',
  attachmentGeneration: 3
};
const queued = deferredBindingContext.result({
  relayId: 'queued-exact', text: 'bounded task', exactBinding: queuedBinding
});
if (!queued.ok || deferredItems.length !== 1
    || JSON.stringify(deferredItems[0].exactBinding) !== JSON.stringify(queuedBinding)) {
  throw new Error('deferred relay lost its exact binding tuple');
}
console.log('1 deferred exact-binding preservation fence PASS');

const recoveryStart = content.indexOf('let relayExecutionRecoveryPromise = null;');
const recoveryEnd = content.indexOf('chrome.runtime.onMessage.addListener(', recoveryStart);
if (recoveryStart < 0 || recoveryEnd <= recoveryStart) {
  throw new Error('content reload recovery helper missing');
}
let durableClears = 0;
let durableDrains = 0;
const durableRecoveryContext = vm.createContext({
  result: null,
  loadRelayExecution: () => ({
    relayId: 'bootstrap-completed', phase: 'submitted',
    conversationKey: 'conversation-b'
  }),
  currentConversationKey: () => 'conversation-b',
  relayPendingStatus: async () => ({ ok:true, found:false, completed:true,
    resultHash:'durable-hash' }),
  clearRelayExecution: () => { durableClears += 1; },
  drainDeferredRelayQueue: async () => { durableDrains += 1; },
  deliverTrackedRelayResultWithRetry: async () => {
    throw new Error('durable receipt must not be replayed');
  },
});
vm.runInContext(content.slice(recoveryStart, recoveryEnd)
  + ';result=recoverRelayExecutionAfterReload;', durableRecoveryContext);
(async () => {
  await durableRecoveryContext.result();
  if (durableClears !== 1 || durableDrains !== 1) {
    throw new Error('durable background receipt did not clear stale content completion');
  }
  console.log('1 durable submitted/completed receipt recovery PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });

const drainStart = content.indexOf('async function drainDeferredRelayQueue(');
const drainEnd = content.indexOf('const relayNetworkStartWaiters', drainStart);
if (drainStart < 0 || drainEnd <= drainStart) {
  throw new Error('content drainDeferredRelayQueue helper missing');
}
let legacyDeferredItems = [{ relayId: 'orch.send.legacy-no-binding', text: 'old task' }];
let legacyDrainSubmits = 0;
const legacyDrainContext = vm.createContext({
  result: null,
  loadRelayExecution: () => null,
  isGenerating: () => false,
  loadDeferredRelayQueue: () => legacyDeferredItems,
  saveDeferredRelayQueue: (items) => { legacyDeferredItems = items; },
  beginRelayExecution: async () => { legacyDrainSubmits += 1; return { ok: true }; },
  scheduleDeferredRelayDrain() {},
});
vm.runInContext(content.slice(drainStart, drainEnd)
  + ';result=drainDeferredRelayQueue;', legacyDrainContext);
(async () => {
  const dropped = await legacyDrainContext.result();
  if (dropped.dropped !== true || dropped.reason !== 'ORCHESTRATION_DEFERRED_BINDING_MISSING'
      || legacyDrainSubmits !== 0 || legacyDeferredItems.length !== 0) {
    throw new Error('legacy unbound orchestration queue item was eligible for late submit');
  }
  console.log('1 legacy unbound deferred relay late-submit fence PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });

const submitStart = content.indexOf('async function submitEditor(');
const submitEnd = content.indexOf('async function waitForReply(', submitStart);
if (submitStart < 0 || submitEnd <= submitStart) throw new Error('content submitEditor helper missing');
let clicked = 0;
let fenced = 0;
let activated = 0;
const editor = { focus() {}, dispatchEvent() {} };
const button = { click() { clicked += 1; } };
const submitContext = vm.createContext({
  result: null, editor, button,
  RelayCore: { normalizeMessageText: (value) => String(value) },
  getEditor: () => editor,
  editorDraftText: () => 'bounded task',
  waitForReadySendButton: async () => button,
  findReadySendButton: () => button,
  KeyboardEvent: function KeyboardEvent() {},
});
vm.runInContext(content.slice(submitStart, submitEnd) + ';result=submitEditor;', submitContext);
(async () => {
  await submitContext.result(editor, {
    expectedText: 'bounded task',
    beforeSubmit: async () => { fenced += 1; return { ...expected }; },
    beforeActivation: async (attestation) => { activated += 1; return attestation; },
  });
  if (fenced !== 1 || activated !== 1 || clicked !== 1) {
    throw new Error('pre-click exact fence and activation checkpoint did not run once');
  }
  try {
    await submitContext.result(editor, {
      expectedText: 'bounded task',
      beforeSubmit: async () => { throw new Error('TARGET_BINDING_CHANGED_BEFORE_SUBMIT'); },
    });
  } catch (error) {
    if (String(error.message || error) !== 'TARGET_BINDING_CHANGED_BEFORE_SUBMIT') throw error;
  }
  if (clicked !== 1 || activated !== 1) {
    throw new Error('binding mismatch reached the activation checkpoint or send button');
  }
  console.log('2 content pre-click binding/activation fences PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });
