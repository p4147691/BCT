const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const source = fs.readFileSync('domain/delivery_ledger_service.js', 'utf8');
const from = source.indexOf('async function deliveryResponseRead(message) {');
const to = source.indexOf('async function deliveryStatus(message) {', from);
assert(from >= 0 && to > from);
const sha = text => crypto.createHash('sha256').update(text,'utf8').digest('hex');
const responseText = '한글😀\\n원문';
const original = Object.freeze({
  deliveryId:'test-1', workId:'authorized', managerConversationKey:'mgr',
  workerConversationKey:'worker', requestSha256:sha('request'),
  responseText, responseSha256:sha(responseText), responseLength:responseText.length
});
let mirror = {'test-1':original};
let reads = 0;
const ctx = vm.createContext({
  deliveryId: x => x,
  readDeliveryLedgerMirror: async () => {reads++;return mirror},
  relaySha256: async x => sha(x)
});
vm.runInContext(source.slice(from,to) + '\nglobalThis.read=deliveryResponseRead;',ctx);
(async()=>{
  const request = {deliveryId:'test-1',workId:'authorized',managerConversationKey:'mgr',
    workerConversationKey:'worker',requestSha256:sha('request')};
  const originalJSON=JSON.stringify(mirror);
  const good=await ctx.read(request);
  assert.equal(good.ok,true);
  assert.equal(good.responseText,responseText);
  assert.equal(good.responseLength,responseText.length);
  assert.equal(good.responseSha256,sha(responseText));
  assert.equal(JSON.stringify(mirror),originalJSON);
  assert.equal((await ctx.read({...request,requestSha256:sha('wrong')})).code,'ACCESS_DENIED');
  mirror={'test-1':{...original,responseText:undefined}};
  assert.equal((await ctx.read(request)).code,'NOT_FOUND');
  mirror={'test-1':{...original,responseSha256:sha('tampered')}};
  assert.equal((await ctx.read(request)).code,'INTEGRITY_MISMATCH');
  mirror={};
  assert.equal((await ctx.read(request)).code,'NOT_RETAINED');
  assert.equal(reads,5);
  console.log('delivery response read-only focused: PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
