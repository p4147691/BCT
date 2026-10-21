const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/domain/diagnostic_support.js`, 'utf8');
const conversationKey = '6ad75568-a1b2-c3d4-e5f6-123456789012';
const tab = {
  id: 42, windowId: 7,
  url: `https://chatgpt.com/c/${conversationKey}`,
  title: 'Bound conversation',
};

function createHarness() {
  const state = {
    settings: { instanceId: 'instance-1' },
    registrations: {},
    bindingSubmitLeases: {},
  };
  const writes = [];
  const context = vm.createContext({
    console,
    bindingLeaseMutationChain: Promise.resolve(),
    endpointSessionId: 'session-1',
    BINDING_SUBMIT_LEASES_KEY: 'bindingSubmitLeasesV1',
    loadState: async () => state,
    stateRepository: { setLocal: async (patch) => writes.push(patch) },
    browserGateway: { getExactTab: async (tabId) => {
      if (Number(tabId) !== tab.id) throw new Error('missing');
      return { ...tab };
    } },
    isChatTab: (value) => String(value?.url || '').startsWith('https://chatgpt.com/'),
    RelayCore: {
      normalizeRole: (value) => String(value || '').trim().toUpperCase(),
      conversationKey: (url) => /\/c\/([^/?#]+)/.exec(url)?.[1] || '',
    },
    Date,
    JSON,
    Number,
    Object,
    String,
    Promise,
    Error,
    RegExp,
  });
  vm.runInContext(source, context, { filename: 'diagnostic_support.js' });
  return { context, state, writes };
}

(async () => {
  const harness = createHarness();
  const request = {
    to: 'bb_mgr',
    instanceId: 'instance-1',
    sessionId: 'session-1',
    tabId: 42,
    conversationKey,
    bindingReceiptId: 'RCB-AAAAAAAAAAAA',
  };
  const first = await harness.context.bindExactConversation(request);
  assert.equal(first.ok, true);
  assert.equal(first.binding.logicalNode, 'BB_MGR');
  assert.equal(first.binding.instanceId, 'instance-1');
  assert.equal(first.binding.sessionId, 'session-1');
  assert.equal(first.binding.tabId, 42);
  assert.equal(first.binding.conversationKey, conversationKey);
  assert.equal(harness.state.registrations.BB_MGR.authorization, 'ACT_CONVERSATION_BIND');
  assert.equal(harness.writes.length, 1);

  const replay = await harness.context.bindExactConversation(request);
  assert.equal(replay.ok, true);
  assert.equal(replay.binding.bindingReceiptId, 'RCB-AAAAAAAAAAAA');

  await assert.rejects(
    harness.context.bindExactConversation({ ...request, instanceId: 'instance-2' }),
    /CONVERSATION_BIND_INSTANCE_MISMATCH/
  );
  await assert.rejects(
    harness.context.bindExactConversation({ ...request, sessionId: 'session-2' }),
    /CONVERSATION_BIND_SESSION_MISMATCH/
  );
  await assert.rejects(
    harness.context.bindExactConversation({ ...request, to: 'bb_w1' }),
    /CONVERSATION_ALREADY_BOUND/
  );
  assert.equal(Object.keys(harness.state.registrations).length, 1);

  console.log('conversation binding service v1: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
