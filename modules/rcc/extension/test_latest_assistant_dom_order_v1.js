'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('content/conversation_dom.js', 'utf8');
const start = source.indexOf('function getMessageUnits(');
const end = source.indexOf('function getConversationTurns(', start);
assert(start >= 0 && end > start);
const old = { id: 'older-assistant' };
const latest = { id: 'latest-assistant' };
let calls = 0;
const root = {
  querySelectorAll(selectors) {
    calls++;
    assert(selectors.includes(', '), 'multi-markup selectors must form ONE DOM-ordered query');
    return [old, latest];
  }
};
const ctx = { canonicalMessageUnit: (node) => node,
  messageUnitRole: () => 'assistant', document: root };
vm.createContext(ctx);
vm.runInContext(source.slice(start, end), ctx);
const observed = ctx.getMessageUnits('assistant', root);
assert.equal(calls, 1);
assert.equal(observed.length, 2);
assert.equal(observed[observed.length - 1], latest);
console.log('latest assistant DOM order: PASS');
