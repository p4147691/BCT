const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(
  require('node:path').join(__dirname, 'content/conversation_dom.js'), 'utf8'
);

function slice(start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first);
  assert(first >= 0 && last > first, `missing source boundary ${start}`);
  return source.slice(first, last);
}

let stopPresent = false;
let streamPresent = false;
let completionState = '';
let completionAction = false;
let sameLatestTurn = true;

const assistant = {
  matches() { return streamPresent; },
  querySelector() { return streamPresent ? {} : null; },
};
const latestTurn = {
  contains(value) { return sameLatestTurn && value === assistant; },
};
const context = vm.createContext({
  document: {querySelector() { return stopPresent ? {} : null; }},
  getConversationTurns: () => [latestTurn],
  lastAssistantNode: () => assistant,
  turnCompletionState: () => completionState,
  hasCompletionAction: () => completionAction,
});

vm.runInContext(
  slice('function latestConversationTurnHasTerminalProof(', 'function turnHasStopAction(')
    + slice('function isGenerating(', 'function isSendReady(')
    + ';globalThis.isGeneratingForTest=isGenerating;',
  context,
);

stopPresent = true;
completionState = 'streaming';
completionAction = true;
assert.equal(context.isGeneratingForTest(), true,
  'a send/copy control never overrides a non-terminal latest turn');

completionState = 'complete';
completionAction = false;
assert.equal(context.isGeneratingForTest(), true,
  'complete state alone cannot override a stop marker');

completionAction = true;
assert.equal(context.isGeneratingForTest(), false,
  'same-turn complete state plus completion action retires an inert stop marker');

sameLatestTurn = false;
assert.equal(context.isGeneratingForTest(), true,
  'terminal proof from a different turn cannot authorize a new submission');

sameLatestTurn = true;
stopPresent = false;
streamPresent = true;
completionState = 'running';
assert.equal(context.isGeneratingForTest(), true,
  'an active streaming marker remains busy');

completionState = 'complete';
completionAction = true;
assert.equal(context.isGeneratingForTest(), false,
  'two exact terminal signals retire an inert streaming marker too');

streamPresent = false;
completionState = '';
completionAction = false;
assert.equal(context.isGeneratingForTest(), false,
  'absence of stop and streaming markers remains idle');

console.log('terminal idle proof v1: PASS (7/7)');
