const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const src = fs.readFileSync('content/content_router.js','utf8');
const a = src.indexOf("if (message.type === 'relay:deliveryRecoveryProof') {");
const b = src.indexOf("if (message.type === 'relay:activityProbe')",a);
assert(a >= 0 && b > a);
const proofCode = src.slice(a,b);
const sha = v => crypto.createHash('sha256').update(v).digest('hex');
const worker = '22222222-2222-2222-2222-222222222222';
const deliveryId = 'original-delivery-001';
const text = 'exact original';
let record = {relayId:deliveryId,conversationKey:worker,submittedText:text,
  phase:'submit-activated',beforeTurnKeys:['old'],routeTurnKey:''};
let current = worker;
let generating = false;
let turnEvidence = {ok:true,turnKey:'new-user-key',turn:{id:'new-user-key'}};
let actualReply = 'finished worker answer';
async function run(request = {}) {
  return new Promise((resolve,reject) => {
    const context = vm.createContext({
      message:{type:'relay:deliveryRecoveryProof',deliveryId,conversationKey:worker,
        requestSha256:sha(text),...request},
      sendResponse: resolve,
      loadRelayExecution: () => record, currentConversationKey: () => current,
      newChatTextSha256: async v => sha(v),
      resolveRoutedTurn: () => turnEvidence,
      submittedPromptMatchesTurn: () => true,
      isGenerating: () => generating,
      turnGenerationInterrupted: () => false,
      recoverCompletedReplyFromDom: () => actualReply,
      Promise
    });
    try { vm.runInContext('(function(){'+proofCode+'})()',context); } catch (e) {reject(e)}
  });
}
(async () => {
  const okay = await run();
  assert.equal(okay.ok,true);
  assert.equal(okay.turnKey,'new-user-key');
  assert.equal(okay.requestSha256,sha(text));
  assert.equal(okay.responseSha256,sha(actualReply));
  assert.equal(okay.responseLength,actualReply.length);
  assert.equal(record.phase,'submit-activated');
  const check = async name => assert.equal((await run()).ok,false,name);
  generating = true; await check('still streaming'); generating = false;
  record = {...record,phase:'submit-intent'}; await check('not activated');
  record = {...record,phase:'submit-activated',relayId:'different'}; await check('wrong original id');
  record = {...record,relayId:deliveryId,submittedText:'modified'}; await check('wrong SHA');
  record = {...record,submittedText:text};
  current = 'unrelated'; await check('wrong conversation'); current=worker;
  turnEvidence = {ok:false,reason:'MISSING'}; await check('unproven turn');
  turnEvidence = {ok:true,turnKey:'new-user-key',turn:{id:'new-user-key'}};
  actualReply = ''; await check('no completed reply');
  console.log('delivery recovery original content proof v1: PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
