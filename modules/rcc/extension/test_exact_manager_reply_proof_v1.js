const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');

const src = fs.readFileSync('content/content_router.js', 'utf8');
const a = src.indexOf("if (message.type === 'relay:exactReplyProof') {");
const b = src.indexOf("if (message.type === 'relay:activityProbe')", a);
assert(a >= 0 && b > a);
const proofCode = src.slice(a, b);
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const manager = '11111111-1111-1111-1111-111111111111';
const deliveryId = 'delivery-manager-terminal-001';
const submittedText = 'one exact Manager return';
const responseText = 'completed Manager decision';
const turn = { querySelector: () => ({}) };

let current = manager;
let matches = [turn];
let interrupted = false;
let generating = false;
let completionState = 'complete';
let assistantText = responseText;

async function run(overrides = {}) {
  return new Promise((resolve, reject) => {
    const context = vm.createContext({
      message: {
        type: 'relay:exactReplyProof', deliveryId,
        conversationKey: manager, submittedSha256: sha(submittedText),
        expectedResponseSha256: sha(responseText),
        expectedResponseLength: responseText.length, ...overrides,
      },
      sendResponse: resolve,
      currentConversationKey: () => current,
      exactUserTurnsBySubmittedSha256: async () => matches,
      turnGenerationInterrupted: () => interrupted,
      turnCompletionState: () => completionState,
      turnIsGenerating: () => generating,
      assistantCandidatesForTurn: () => [{ text: assistantText }],
      RelayCore: { selectAssistantCandidate: candidates =>
        ({ ok: candidates.length === 1, candidate: candidates[0] }) },
      newChatTextSha256: async value => sha(value),
      turnIdentity: () => 'semantic:user:manager-terminal-001',
      Number, Promise,
    });
    try { vm.runInContext('(function(){' + proofCode + '})()', context); }
    catch (error) { reject(error); }
  });
}

(async () => {
  const okay = await run();
  assert.equal(okay.ok, true);
  assert.equal(okay.deliveryId, deliveryId);
  assert.equal(okay.responseText, responseText);
  assert.equal(okay.responseSha256, sha(responseText));
  assert.equal(okay.responseLength, responseText.length);

  matches = []; assert.equal((await run()).ok, false);
  matches = [turn, turn]; assert.equal((await run()).ok, false);
  matches = [turn];
  interrupted = true; assert.equal((await run()).ok, false); interrupted = false;
  generating = true; completionState = 'streaming';
  assert.equal((await run()).ok, false);
  generating = false; completionState = 'complete';
  assistantText = 'changed';
  const changed = await run();
  assert.equal(changed.ok, false);
  assert.equal(changed.error, 'RELAY_EXACT_REPLY_IDENTITY_MISMATCH');
  assistantText = responseText;
  current = 'unrelated'; assert.equal((await run()).ok, false);

  console.log('exact Manager reply proof v1: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
