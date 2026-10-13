const assert = require('node:assert/strict');
const fs = require('node:fs');

const source = fs.readFileSync('background.js', 'utf8');
const start = source.indexOf('function bootstrapSubmissionEvidenceIsExact(');
const end = source.indexOf('function waitForCreatedConversationIdentity(', start);
assert(start >= 0 && end > start, 'bootstrap evidence function missing');
const evidenceIsExact = new Function(
  source.slice(start, end) + '\nreturn bootstrapSubmissionEvidenceIsExact;'
)();

const pending = {
  bootstrapCreatedTab: true,
  tabId: 10,
  windowId: 11,
  networkStartedAt: 123,
  networkRequestId: 'request-1',
};
const recovered = {
  ok: true,
  tabId: 10,
  windowId: 11,
  conversationKey: 'conversation-1234',
  submittedText: 'exact message',
};
const expected = {tabId: 10, windowId: 11, submittedText: 'exact message'};
assert.equal(evidenceIsExact(pending, recovered, expected), true);
assert.equal(evidenceIsExact({...pending, networkStartedAt: 0}, recovered, expected), false);
assert.equal(evidenceIsExact({...pending, networkRequestId: ''}, recovered, expected), false);
assert.equal(evidenceIsExact(pending, {...recovered, conversationKey: ''}, expected), false);
assert.equal(evidenceIsExact(pending, {...recovered, submittedText: 'other'}, expected), false);
assert.equal(evidenceIsExact(pending, {...recovered, tabId: 12}, expected), false);
assert.equal(evidenceIsExact(pending, {...recovered, windowId: 12}, expected), false);

const catchMarker = 'return await recoverBootstrapSubmissionAfterTransportLoss(';
const unknownMarker = "submissionState = 'SUBMIT_UNKNOWN'";
assert(source.indexOf(catchMarker) >= 0, 'transport-loss recovery call missing');
assert(source.indexOf(catchMarker) < source.indexOf(unknownMarker, source.indexOf(catchMarker)),
  'transport-loss recovery must run before SUBMIT_UNKNOWN persistence');
assert(source.includes("submissionState = 'SUBMITTED_RECOVERED_AFTER_NAVIGATION'"));
assert(source.includes("state: 'SUBMITTED_RECOVERED_AFTER_NAVIGATION'"));
assert(source.includes('new MutationObserver(check)'));
console.log('Issue57 navigation ACK recovery: 7 negative fences PASS');
