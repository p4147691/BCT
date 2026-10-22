const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const source = fs.readFileSync('domain/delivery_ledger_service.js', 'utf8');
const from = source.indexOf('async function deliveryRecoveryInspect(message) {');
assert(from >= 0);
const code = source.slice(from);
const sha = value => crypto.createHash('sha256').update(value, 'utf8').digest('hex');
const managerKey = '11111111-1111-1111-1111-111111111111';
const workerKey = '22222222-2222-2222-2222-222222222222';
const requestSha256 = sha('exact original');
const deliveryIdValue = 'original-delivery-001';
const responseText = 'exact completed reply';
const fingerprint = sha(JSON.stringify([deliveryIdValue, managerKey, workerKey, requestSha256]));
const record = {
  state: 'NEEDS_REVIEW', deliveryId: deliveryIdValue, managerConversationKey: managerKey,
  workerConversationKey: workerKey, requestSha256, fingerprint
};
let calls = [];
let observed = {
  ok: true, deliveryId: deliveryIdValue, conversationKey: workerKey,
  requestSha256, turnKey: 'semantic:user', phase: 'submit-activated',
  responseText, responseSha256: sha(responseText), responseLength: responseText.length
};
const context = vm.createContext({
  deliveryId: v => v, deliveryConversationKey: v => v,
  readDeliveryLedgerMirror: async () => ({ [deliveryIdValue]: record }),
  relaySha256: async value => sha(value), getChatTabs: async () => [
    {id: 1, windowId: 11, url: 'https://chatgpt.com/c/' + managerKey},
    {id: 2, windowId: 11, url: 'https://chatgpt.com/c/' + workerKey}
  ],
  deliveryTabs: (tabs, m, w) => {
    assert.equal(m, managerKey); assert.equal(w, workerKey);
    return {manager:tabs[0], worker:tabs[1]};
  },
  sendToChatTab: async (id, message) => {
    calls.push([id, message]);
    return observed;
  }
});
vm.runInContext(code + '\nglobalThis.inspect=deliveryRecoveryInspect;', context);
(async () => {
  const base = {deliveryId:deliveryIdValue, managerConversationKey:managerKey,
    workerConversationKey:workerKey, requestSha256};
  const okay = await context.inspect(base);
  assert.equal(okay.ok, true);
  assert.equal(okay.reconciled, false);
  assert.equal(okay.responseText, responseText);
  assert.equal(okay.originalTurnKey, 'semantic:user');
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 2);
  assert.equal(calls[0][1].type, 'relay:deliveryRecoveryProof');
  assert.equal(record.state, 'NEEDS_REVIEW', 'original mirror may not mutate');
  for (const [key, invalid] of [['responseSha256', '0'.repeat(64)],
    ['requestSha256', '0'.repeat(64)], ['conversationKey', managerKey],
    ['phase', 'submit-intent'], ['turnKey', ''], ['responseLength', 2]]) {
    const copy = {...observed, [key]:invalid};
    observed = copy;
    const rejected = await context.inspect(base);
    assert.equal(rejected.ok, false, 'tamper must be rejected: '+key);
  }
  observed = {...observed, ok:true};
  assert.equal((await context.inspect({...base,requestSha256:'0'.repeat(64)})).ok, false);
  assert.equal(record.state,'NEEDS_REVIEW');
  console.log('delivery recovery inspect v1: PASS');
})().catch(e => {console.error(e); process.exitCode=1});
