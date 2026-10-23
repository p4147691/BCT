const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('content/content_router.js', 'utf8');
const start = source.indexOf("if (message.type === 'relay:retireComposerDraft') {");
const end = source.indexOf("if (message.type === 'relay:retireExecution')", start);
assert(start >= 0 && end > start);
const handler = source.slice(start, end);
const worker = '22222222-2222-2222-2222-222222222222';
const deliveryId = 'superseded-delivery';
const text = '[/BCT_DELIVERY_WORKER_V1] exact stale draft';
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');

async function run(overrides = {}) {
  let record = overrides.record === undefined ? {
    relayId: deliveryId, conversationKey: worker, submittedText: text,
    phase: 'submit-activated', beforeTurnKeys: ['old'], routeTurnKey: '',
  } : overrides.record;
  let draft = overrides.draft === undefined ? text : overrides.draft;
  let response;
  const context = vm.createContext({
    message: {
      type: 'relay:retireComposerDraft', conversationKey: worker,
      expectedDraftSha256: sha256(text), supersededDeliveryId: deliveryId,
      ...(overrides.message || {}),
    },
    currentConversationKey: () => overrides.current || worker,
    isGenerating: () => overrides.generating === true,
    loadRelayExecution: () => record,
    clearRelayExecution: (id) => { if (record?.relayId === id) record = null; },
    retiredRelayExecutions: new Set(),
    resolveRoutedTurn: () => overrides.routed || {
      ok: false, terminal: false, reason: 'ROUTE_TURN_NOT_RESOLVED',
    },
    getEditor: () => (overrides.noEditor ? null : {}),
    editorDraftText: () => draft,
    setEditorText: (_editor, value) => { if (!overrides.clearFails) draft = value; },
    newChatTextSha256: async (value) => sha256(value),
    sendResponse: (value) => { response = value; },
    setTimeout: (fn) => { fn(); },
    Promise,
  });
  vm.runInContext(`(function(){${handler}})()`, context);
  for (let attempt = 0; attempt < 20 && !response; attempt += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  return { response, record, draft };
}

(async () => {
  const exact = await run();
  assert.equal(exact.response.ok, true);
  assert.equal(exact.response.retiredExecutionId, deliveryId);
  assert.equal(exact.record, null);
  assert.equal(exact.draft, '');

  for (const [name, overrides, error] of [
    ['wrong id', {record: {relayId: 'other', conversationKey: worker,
      submittedText: text, phase: 'submit-activated'}}, 'RELAY_DRAFT_RETIRE_ACTIVE_IDENTITY_MISMATCH'],
    ['wrong hash', {record: {relayId: deliveryId, conversationKey: worker,
      submittedText: 'different', phase: 'submit-activated'}}, 'RELAY_DRAFT_RETIRE_ACTIVE_HASH_MISMATCH'],
    ['submitted phase', {record: {relayId: deliveryId, conversationKey: worker,
      submittedText: text, phase: 'submitted'}}, 'RELAY_DRAFT_RETIRE_ACTIVE_IDENTITY_MISMATCH'],
    ['completed phase', {record: {relayId: deliveryId, conversationKey: worker,
      submittedText: text, phase: 'completed'}}, 'RELAY_DRAFT_RETIRE_ACTIVE_IDENTITY_MISMATCH'],
    ['routed turn', {routed: {ok: true, turnKey: 'new', turn: {}}},
      'RELAY_DRAFT_RETIRE_ACTIVE_ROUTE_NOT_ABSENT'],
  ]) {
    const result = await run(overrides);
    assert.equal(result.response.effectState, 'NOT_APPLIED', name);
    assert.equal(result.response.error, error, name);
    assert.equal(result.draft, text, name);
  }

  const uncertain = await run({clearFails: true});
  assert.equal(uncertain.response.effectState, 'UNKNOWN');
  assert.equal(uncertain.response.error, 'RELAY_DRAFT_RETIRE_CLEAR_UNPROVEN');
  console.log('exact active draft retirement v2: PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });
