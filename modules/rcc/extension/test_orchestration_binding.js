const fs = require('fs');
const vm = require('vm');
const { webcrypto } = require('crypto');

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
  chrome, crypto: webcrypto, URL, console, process, liveTabs,
  setTimeout() { return 1; }, clearTimeout() {},
  TextEncoder, TextDecoder,
});
vm.runInContext(fs.readFileSync('relay_core.js', 'utf8'), context);
const background = fs.readFileSync('background.js', 'utf8');
const tests = String.raw`
;(async () => {
  await endpointSessionReady;
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

  console.log('4 orchestration binding fences PASS; 3 content authorization fences PASS; 7 lease interleaving fences PASS');
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

const submitStart = content.indexOf('async function submitEditor(');
const submitEnd = content.indexOf('async function waitForReply(', submitStart);
if (submitStart < 0 || submitEnd <= submitStart) throw new Error('content submitEditor helper missing');
let clicked = 0;
let fenced = 0;
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
  });
  if (fenced !== 1 || clicked !== 1) throw new Error('pre-click exact fence did not run once');
  try {
    await submitContext.result(editor, {
      expectedText: 'bounded task',
      beforeSubmit: async () => { throw new Error('TARGET_BINDING_CHANGED_BEFORE_SUBMIT'); },
    });
  } catch (error) {
    if (String(error.message || error) !== 'TARGET_BINDING_CHANGED_BEFORE_SUBMIT') throw error;
  }
  if (clicked !== 1) throw new Error('binding mismatch still clicked the send button');
  console.log('2 content pre-click binding fences PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });
