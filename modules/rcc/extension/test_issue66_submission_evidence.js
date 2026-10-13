const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('content.js','utf8');
const marker = 'function firstSubmissionEvidence(';
const end = 'function waitForRelaySubmissionAccepted(';
const i=source.indexOf(marker), j=source.indexOf(end,i);
assert(i>=0 && j>i);
const firstSubmissionEvidence = vm.runInNewContext(source.slice(i,j)+'\nfirstSubmissionEvidence');
const deferred=()=>{let resolve,reject; const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
(async()=>{
  {
    const net=deferred(),dom=deferred();
    const result=firstSubmissionEvidence(net.promise,dom.promise);
    dom.resolve(true);
    assert.equal(await result,'exact-user-turn','DOM confirms without network timeout');
    net.reject(new Error('network timeout')); // handled; no stale unhandled rejection
  }
  {
    const net=deferred(),dom=deferred();
    const result=firstSubmissionEvidence(net.promise,dom.promise);
    net.resolve(true);
    assert.equal(await result,'network','network confirms without DOM wait');
    dom.reject(new Error('DOM navigation detached')); // handled
  }
  {
    const net=deferred(),dom=deferred();
    const result=firstSubmissionEvidence(net.promise,dom.promise);
    net.reject(new Error('network missing'));
    dom.resolve(true);
    assert.equal(await result,'exact-user-turn','positive DOM survives network error');
  }
  {
    const net=deferred(),dom=deferred();
    const result=firstSubmissionEvidence(net.promise,dom.promise);
    net.reject(new Error('network missing'));
    dom.reject(new Error('no user turn'));
    await assert.rejects(result,/All promises were rejected/);
  }
  assert(source.includes('waitForExactUserSubmission(requestedText, beforeUserCount, 5000)'));
  assert(source.includes("const networkStarted = submissionEvidence === 'network';"));
  assert(source.includes("allowKeyboardFallback: message.bootstrapCreatedTab !== true"));
  console.log('Issue66 event-driven parallel submission evidence: 4 tests PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
