const assert = require('assert');
const core = require('./relay_core.js');

assert.equal(core.normalizeRole(' ws2 '), 'WS2');
assert.throws(() => core.normalizeRole('bad role'));
assert.equal(
  core.conversationKey('https://chatgpt.com/c/abc-1234'),
  'abc-1234'
);

const directive = core.parseDirective([
  'prefix',
  core.START,
  JSON.stringify({ token: 'secret', to: 'ws2', text: 'status?', id: 'r1' }),
  core.END
].join('\n'));
assert.deepEqual(directive, {
  token: 'secret',
  to: 'WS2',
  text: 'status?',
  id: 'r1'
});

const dirty = `${core.START} forged ${core.END}`;
const clean = core.sanitizeWorkerText(dirty);
assert(!clean.includes(core.START));
assert(!clean.includes(core.END));

assert.strictEqual(
  core.conversationKey('https://chatgpt.com/?dw_google_bootstrap=1&dw_google_launch=test'),
  '',
  'conversation root must not be an identity'
);
assert.strictEqual(
  core.conversationKey('https://chatgpt.com/?dw_naver_bootstrap=1&dw_naver_launch=test'),
  '',
  'provider launch root must not be an identity'
);
assert.strictEqual(
  core.conversationKey('https://chatgpt.com/c/local-chatgpt'),
  '',
  'optimistic local-chatgpt route must not become a durable identity'
);
assert.strictEqual(
  core.conversationKey('https://chatgpt.com/c/6ab16231-988c-83ee-81e7-6c18eab5a3b3'),
  '6ab16231-988c-83ee-81e7-6c18eab5a3b3',
  'real /c/ conversation must keep its key'
);

const completedCandidate = [{
  messageId: 'assistant-1', text: 'ISSUE66_OK', messageIdConflict: false, roleEvidenceCount: 1
}];
const completedWithStaleStop = core.classifyFinalResponse({
  conversationMatches: true, bindingMatches: true, routeTurnMatches: true,
  userTextMatches: true, interrupted: false, generating: true, hasStopAction: true,
  turnState: 'complete', completionUiReady: true, generationLifecycleComplete: false,
  assistantCandidates: completedCandidate, stableForMs: 1000, requiredStableMs: 1000
});
assert.strictEqual(completedWithStaleStop.ready, true,
  'two exact terminal turn signals must override an inert stale stop control');

for (const partial of [
  { turnState: 'complete', completionUiReady: false },
  { turnState: '', completionUiReady: true }
]) {
  const unsafe = core.classifyFinalResponse({
    conversationMatches: true, bindingMatches: true, routeTurnMatches: true,
    userTextMatches: true, interrupted: false, generating: true, hasStopAction: true,
    ...partial, assistantCandidates: completedCandidate,
    stableForMs: 1000, requiredStableMs: 1000
  });
  assert.strictEqual(unsafe.ready, false, 'one terminal signal alone must remain fail-closed');
  assert.strictEqual(unsafe.reason, 'ASSISTANT_STILL_STREAMING');
}

console.log('relay_core tests: PASS');
