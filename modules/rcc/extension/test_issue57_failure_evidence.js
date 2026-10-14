const assert = require('assert');
const fs = require('fs');
const core = require('./relay_core.js');
const content = fs.readFileSync('content.js', 'utf8');
const background = fs.readFileSync('background.js', 'utf8');
assert(content.includes("phase: 'FINAL_DOM_VALIDATION'"));
assert(content.includes("networkError: networkReason"));
assert(content.includes("domError: domReason"));
assert(content.includes("signal?.ok === true ? 'COMPLETE' : 'UNKNOWN'"));
assert(content.includes("result.failureEvidence = error.relayFailureEvidence"));
assert(background.includes("failureEvidence: result?.failureEvidence ?"));
assert(background.includes("failureEvidence: payload.failureEvidence || null"));
assert(background.includes("submitState: String(receipt.submitState || '')"));
const marker = "function boundedRelayResultPayload(result) {";
const begin = background.indexOf(marker);
const end = background.indexOf("async function relaySha256", begin);
assert(begin >= 0 && end > begin);
const fn = new Function(background.slice(begin, end) + "\nreturn boundedRelayResultPayload;");
const bounded = fn();
const payload = bounded({ ok:false, error:'net::ERR_ABORTED', failureEvidence: {
  phase:'FINAL_DOM_VALIDATION', networkError:'net::ERR_ABORTED',
  domError:'RELAY_FINAL_DOM_UNKNOWN:ROUTE_TURN_NOT_RESOLVED', networkSignal:'FAILED'
}});
assert.strictEqual(payload.failureEvidence.networkError, 'net::ERR_ABORTED');
assert.strictEqual(payload.failureEvidence.domError, 'RELAY_FINAL_DOM_UNKNOWN:ROUTE_TURN_NOT_RESOLVED');
assert.strictEqual(payload.failureEvidence.phase, 'FINAL_DOM_VALIDATION');
assert.strictEqual(payload.failureEvidence.networkSignal, 'FAILED');
assert.strictEqual(bounded({ok:true,reply:'ok'}).failureEvidence,null);
const oversized = bounded({ ok:false, failureEvidence: {
  phase:'p'.repeat(100), networkError:'n'.repeat(500),
  domError:'d'.repeat(500), networkSignal:'s'.repeat(100)
}});
assert.strictEqual(oversized.failureEvidence.phase.length, 80);
assert.strictEqual(oversized.failureEvidence.networkError.length, 300);
assert.strictEqual(oversized.failureEvidence.domError.length, 300);
assert.strictEqual(oversized.failureEvidence.networkSignal.length, 40);
const recoverableStart = background.indexOf('function isRecoverableCaptureResult(');
const recoverableEnd = background.indexOf('async function replaceRecoverableResultReceipt', recoverableStart);
assert(recoverableStart >= 0 && recoverableEnd > recoverableStart);
const recoverableFn = new Function(
  background.slice(recoverableStart, recoverableEnd) + '\nreturn isRecoverableCaptureResult;'
)();
assert.strictEqual(recoverableFn({
  ok: false,
  error: 'net::ERR_ABORTED',
  failureEvidence: {
    phase: 'FINAL_DOM_VALIDATION',
    networkError: 'net::ERR_ABORTED',
    domError: 'RELAY_FINAL_DOM_NOT_READY:ROUTE_TURN_NOT_RESOLVED',
    networkSignal: 'FAILED'
  }
}), true);
assert.strictEqual(typeof core.needsDirectCaptureRecovery, 'function');
assert.strictEqual(core.needsDirectCaptureRecovery({
  ok: false, recovered: false, error: 'RELAY_RECOVERY_DOM_UNKNOWN:ROUTE_TURN_NOT_RESOLVED'
}), true);
assert.strictEqual(core.needsDirectCaptureRecovery({
  ok: true, recovered: true, recoveredReply: ''
}), true);
assert.strictEqual(core.needsDirectCaptureRecovery({
  ok: true, recovered: true, recoveredReply: 'bounded result'
}), false);
assert(background.includes('RelayCore.needsDirectCaptureRecovery(recovered)'));
assert(background.includes('captureRecoveryError'));
console.log('Issue57 failure evidence tests PASS');
