'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, 'content', 'conversation_dom.js'), 'utf8'
);
const start = source.indexOf('function currentReasoningObservation()');
const end = source.indexOf('function isSendReady()', start);
assert.ok(start >= 0 && end > start, 'reasoning observation source boundary');

function observe(buttons, now = 1234) {
  const context = vm.createContext({
    document: {querySelectorAll: () => buttons},
    Date: {now: () => now},
  });
  vm.runInContext(
    source.slice(start, end) + ';globalThis.observe = currentReasoningObservation;',
    context,
  );
  return JSON.parse(JSON.stringify(context.observe()));
}

const exact = {
  getAttribute: (name) => name === 'aria-label' ? 'ChatGPT 모델 선택' : '',
  querySelector: () => ({textContent: 'High'}),
  innerText: '추론 수준\nHigh',
};
assert.deepEqual(observe([exact]), {
  status: 'OBSERVED', level: 'High', source: 'chatgpt-model-selector', observedAt: 1234,
});

const fallback = {
  getAttribute: (name) => name === 'aria-label' ? 'ChatGPT model selector' : '',
  querySelector: () => null,
  innerText: 'Reasoning level\nMedium',
};
assert.equal(observe([fallback]).level, 'Medium');
assert.deepEqual(observe([]), {
  status: 'UNAVAILABLE', level: '', source: 'chatgpt-model-selector',
});

console.log('reasoning observation v1: PASS');
