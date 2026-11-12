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
let stopVisibility = 'visible';
let stopAncestorDisplay = 'block';
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
const stopAncestor = {};
const stop = {parentElement: stopAncestor, getClientRects: () => []};
const context = vm.createContext({
  document: {querySelectorAll() { return stopPresent ? [stop] : []; }},
  getComputedStyle: (element) => element === stop
    ? {display: 'block', visibility: stopVisibility}
    : {display: stopAncestorDisplay, visibility: 'visible'},
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

stopPresent = true;
assert.equal(context.isGeneratingForTest(), true,
  'zero client rects alone do not retire a stop button');

stopAncestorDisplay = 'none';
assert.equal(context.isGeneratingForTest(), false,
  'a stop button in a hidden subtree does not indicate generation');

stopAncestorDisplay = 'block';
stopVisibility = 'hidden';
assert.equal(context.isGeneratingForTest(), false,
  'a CSS-hidden stop button does not indicate generation');

streamPresent = true;
assert.equal(context.isGeneratingForTest(), true,
  'a hidden stop button does not override an active streaming marker');

console.log('terminal idle proof v1: PASS (11/11)');
