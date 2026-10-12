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
  core.conversationKey('https://chatgpt.com/c/6ab16231-988c-83ee-81e7-6c18eab5a3b3'),
  '6ab16231-988c-83ee-81e7-6c18eab5a3b3',
  'real /c/ conversation must keep its key'
);

console.log('relay_core tests: PASS');
