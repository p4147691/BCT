const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('content/content_router.js', 'utf8');
const start = source.indexOf("if (message.type === 'relay:retireExecution') {");
const end = source.indexOf("if (message.type === 'relay:probe')", start);
assert(start >= 0 && end > start);
const handler = source.slice(start, end);
const worker = '22222222-2222-2222-2222-222222222222';
const deliveryId = 'recovered-delivery';
const request = 'request';
const reply = 'exact recovered response';
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');

async function run(overrides = {}) {
  let record = overrides.record === undefined ? {
    relayId: deliveryId, conversationKey: worker, submittedText: request,
    phase: 'submit-activated', beforeTurnKeys: ['old'], routeTurnKey: '',
  } : overrides.record;
  let response;
  const context = vm.createContext({
    message: {
      type: 'relay:retireExecution', relayId: deliveryId,
      conversationKey: worker, expectedRequestSha256: sha256(request),
      expectedResponseSha256: sha256(reply),
      expectedResponseLength: reply.length, ...(overrides.message || {}),
    },
    loadRelayExecution: () => record,
    clearRelayExecution: (id) => { if (!overrides.clearFails && record?.relayId === id) record = null; },
    currentConversationKey: () => overrides.current || worker,
    recoverCompletedReplyFromDom: () => {
      if (overrides.recoveryError) throw new Error(overrides.recoveryError);
      return overrides.reply === undefined ? reply : overrides.reply;
    },
    newChatTextSha256: async (value) => sha256(value),
    retiredRelayExecutions: new Set(),
    scheduleRelayGenerationStateCheck: () => {},
    sendResponse: (value) => { response = value; },
    Promise,
  });
  vm.runInContext(`(function(){${handler}})()`, context);
  for (let attempt = 0; attempt < 20 && !response; attempt += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  return { response, record };
}

(async () => {
  const exact = await run();
  assert.equal(exact.response.ok, true);
  assert.equal(exact.response.effectState, 'APPLIED');
  assert.equal(exact.response.responseSha256, sha256(reply));
  assert.equal(exact.response.requestSha256, sha256(request));
  assert.equal(exact.response.executionAbsent, true);
  assert.equal(exact.record, null);

  const wrongId = await run({record: {
    relayId: 'other', conversationKey: worker, submittedText: 'request',
    phase: 'submit-activated', beforeTurnKeys: ['old'], routeTurnKey: '',
  }});
  assert.equal(wrongId.response.effectState, 'NOT_APPLIED');
  assert.equal(wrongId.response.error, 'RELAY_RETIRE_ID_MISMATCH');
  const wrongRequest = await run({message: {expectedRequestSha256: 'b'.repeat(64)}});
  assert.equal(wrongRequest.response.error, 'RELAY_RETIRE_REQUEST_IDENTITY_MISMATCH');
  const wrongHash = await run({message: {expectedResponseSha256: 'a'.repeat(64)}});
  assert.equal(wrongHash.response.error, 'RELAY_RETIRE_RESPONSE_IDENTITY_MISMATCH');
  const incomplete = await run({recoveryError: 'RELAY_RECOVERY_ASSISTANT_STILL_STREAMING'});
  assert.equal(incomplete.response.effectState, 'NOT_APPLIED');
  const uncertain = await run({clearFails: true});
  assert.equal(uncertain.response.effectState, 'UNKNOWN');
  assert.equal(uncertain.response.error, 'RELAY_RETIRE_CLEAR_UNPROVEN');
  console.log('recovered execution retirement v1: PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });
