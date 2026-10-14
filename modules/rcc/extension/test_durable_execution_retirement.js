const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const content = fs.readFileSync('content.js', 'utf8');
const background = fs.readFileSync('background.js', 'utf8');
const prior = { relayId: 'bootstrap-durable', phase: 'submitted',
  conversationKey: 'conversation-a', submittedText: 'bootstrap only' };

function fixture(options = {}) {
  const storage = new Map([['relayActiveExecutionV1', JSON.stringify(prior)]]);
  let key = prior.conversationKey;
  let reads = 0;
  let editorEntries = 0;
  const status = { ok: true, found: false, completed: true,
    relayId: prior.relayId, resultHash: 'durable-hash', ...options.status };
  const ctx = vm.createContext({
    sessionStorage: { getItem: (k) => storage.get(k),
      setItem: (k, v) => storage.set(k, v), removeItem: (k) => storage.delete(k) },
    currentConversationKey: () => key,
    relayPendingStatus: async () => {
      reads += 1;
      if (options.raceRecord) storage.set('relayActiveExecutionV1', JSON.stringify(options.raceRecord));
      if (options.raceRoute) key = 'conversation-b';
      return status;
    },
    requireExactRelayAuthorization: async () => ({}),
    connectionProblem: () => ({ disconnected: false }),
    recoverRelayExecutionAfterReload: async () => { throw Error('must not recover or replay prior result'); },
    isGenerating: () => false,
    waitForEditor: async () => { editorEntries += 1; throw Error('TEST_EDITOR_BOUNDARY'); },
  });
  const storageStart = content.indexOf('const RELAY_EXECUTION_KEY');
  const storageEnd = content.indexOf('const RELAY_DEFERRED_QUEUE_KEY', storageStart);
  const helperStart = content.indexOf('async function retirePersistedRelayExecution(');
  const beginStart = content.indexOf('async function beginRelayExecution(');
  const beginEnd = content.indexOf('async function executeRelayMessage(', beginStart);
  vm.runInContext(content.slice(storageStart, storageEnd)
    + (helperStart >= 0 ? content.slice(helperStart, beginStart) : '')
    + content.slice(beginStart, beginEnd)
    + ';globalThis.api={beginRelayExecution,saveRelayExecution,loadRelayExecution};', ctx);
  return { ctx, get reads() { return reads; }, get editorEntries() { return editorEntries; } };
}

(async () => {
  const success = fixture();
  await assert.rejects(success.ctx.api.beginRelayExecution({ relayId: 'new-assignment',
    exactBinding: {}, text: 'new task' }), /TEST_EDITOR_BOUNDARY/,
  'real begin path must retire the persisted submitted bootstrap before editor access');
  assert.strictEqual(success.reads, 1);
  assert.strictEqual(success.editorEntries, 1);
  assert.strictEqual(success.ctx.api.loadRelayExecution(), null);
  success.ctx.api.saveRelayExecution({ relayId: 'new-assignment', phase: 'submit-intent' });
  success.ctx.api.saveRelayExecution({ ...prior, phase: 'completed', result: { ok: true } });
  assert.strictEqual(success.ctx.api.loadRelayExecution().relayId, 'new-assignment',
    'late old collector must not resurrect a retired record over the new execution');

  const negatives = [
    { status: { completed: false } }, { status: { ok: false } },
    { status: { found: true } }, { status: { relayId: 'other' } },
    { status: { resultHash: '' } }, { raceRoute: true },
    { raceRecord: { ...prior, phase: 'completed', result: { ok: false } } },
    { raceRecord: { relayId: 'other', phase: 'submitted' } },
  ];
  for (const options of negatives) {
    const f = fixture(options);
    const outcome = await f.ctx.api.beginRelayExecution({ relayId: 'new-assignment', exactBinding: {} });
    assert.strictEqual(outcome.error, 'ORCHESTRATION_TARGET_BUSY');
    assert.strictEqual(outcome.effectState, 'NOT_APPLIED');
    assert.strictEqual(f.editorEntries, 0);
    assert(f.ctx.api.loadRelayExecution(), 'unproven or changed record must remain');
  }

  // Exercise the actual background sender/receipt proof, not a fabricated success alone.
  const handlerStart = background.indexOf("if (message.type === 'relay:getPendingStatus') {");
  const handlerEnd = background.indexOf("if (message.type === 'relay:getState') {", handlerStart);
  const state = { pending: {}, resultReceipts: { [prior.relayId]: {
    resultState: 'RESULT_PERSISTED', tabId: 901, conversationKey: 'conversation-a', resultHash: 'hash'
  } } };
  const bg = vm.createContext({ loadState: async () => state, RelayCore: require('./relay_core.js') });
  vm.runInContext('globalThis.status = async function(message, sender) {'
    + background.slice(handlerStart, handlerEnd) + '};', bg);
  const message = { type: 'relay:getPendingStatus', relayId: prior.relayId };
  const sender = { tab: { id: 901, url: 'https://chatgpt.com/c/conversation-a' } };
  assert.strictEqual((await bg.status(message, sender)).completed, true);
  for (const tab of [{ ...sender.tab, id: 902 },
    { ...sender.tab, url: 'https://chatgpt.com/c/conversation-b' }]) {
    assert.notStrictEqual((await bg.status(message, { tab })).completed, true);
  }
  state.resultReceipts[prior.relayId].resultState = 'PENDING';
  assert.notStrictEqual((await bg.status(message, sender)).completed, true);
  console.log('durable execution retirement tests: PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });
