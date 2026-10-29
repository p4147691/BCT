const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('content/conversation_dom.js', 'utf8');
const start = source.indexOf('function turnUserText(');
const end = source.indexOf('function isVisible(', start);
assert(start >= 0 && end > start, 'route resolver boundary missing');

let conversationKey = 'conversation-new';
let turns = [];
const context = {
  RelayCore: {normalizeMessageText: value => String(value || '').trim()},
  currentConversationKey: () => conversationKey,
  getConversationTurns: () => turns,
  getMessageUnits: (_role, turn) => [turn],
  messageUnitText: turn => turn.text,
  turnIdentity: turn => turn.key,
};
vm.createContext(context);
vm.runInContext(source.slice(start, end) + '\nglobalThis.resolveRoutedTurn = resolveRoutedTurn;', context);

function record(extra = {}) {
  return {
    conversationKey: 'conversation-provisional',
    submittedText: 'exact prompt',
    beforeTurnKeys: [],
    routeTurnKey: '',
    bootstrapCreatedTab: true,
    ...extra,
  };
}

turns = [{key: 'turn-1', text: 'exact prompt'}];
const rebound = record();
const accepted = context.resolveRoutedTurn(rebound);
assert.equal(accepted.ok, true);
assert.equal(accepted.turnKey, 'turn-1');
assert.equal(rebound.conversationKey, 'conversation-new');

// A bootstrap receiver may persist an interim route UUID before the user
// turn mounts. That cannot be treated as a different conversation, and
// cannot be called SUBMITTED until the unique exact turn is present.
turns = [];
const provisional = record({conversationKey: 'route-before-user-turn'});
const provisionalPending = context.resolveRoutedTurn(provisional);
assert.equal(provisionalPending.ok, false);
assert.equal(provisionalPending.terminal, false);
assert.equal(provisionalPending.reason, 'BOOTSTRAP_ROUTE_TURN_PENDING');
turns = [{key: 'turn-proven', text: 'exact prompt'}];
const provisionalAccepted = context.resolveRoutedTurn(provisional);
assert.equal(provisionalAccepted.ok, true);
assert.equal(provisionalAccepted.turnKey, 'turn-proven');
assert.equal(provisional.conversationKey, 'conversation-new');

// ChatGPT can publish its UUID before it mounts the first user turn.  Only a
// truly blank bootstrap may wait through that transient state; it must still
// require the one exact turn before binding the new conversation UUID.
turns = [];
const blankBootstrap = record({conversationKey: ''});
const pending = context.resolveRoutedTurn(blankBootstrap);
assert.equal(pending.ok, false);
assert.equal(pending.terminal, false);
assert.equal(pending.reason, 'BOOTSTRAP_ROUTE_TURN_PENDING');
assert.equal(blankBootstrap.conversationKey, '');
turns = [{key: 'turn-after-route', text: 'exact prompt'}];
const boundAfterPending = context.resolveRoutedTurn(blankBootstrap);
assert.equal(boundAfterPending.ok, true);
assert.equal(blankBootstrap.conversationKey, 'conversation-new');

// Placeholder containers can appear while the first user turn is still mounting.
// Wait for the exact user turn; do not promote from a UUID or empty container.
turns = [{key: 'placeholder', text: ''}];
const placeholderBootstrap = record({conversationKey: ''});
const placeholderPending = context.resolveRoutedTurn(placeholderBootstrap);
assert.equal(placeholderPending.terminal, false);
assert.equal(placeholderPending.reason, 'BOOTSTRAP_ROUTE_TURN_PENDING');
assert.equal(placeholderBootstrap.conversationKey, '');
turns = [{key: 'turn-after-placeholder', text: 'exact prompt'}];
const placeholderBound = context.resolveRoutedTurn(placeholderBootstrap);
assert.equal(placeholderBound.ok, true);
assert.equal(placeholderBound.turnKey, 'turn-after-placeholder');
assert.equal(placeholderBootstrap.conversationKey, 'conversation-new');

assert.equal(context.resolveRoutedTurn(record({bootstrapCreatedTab: false})).reason,
  'CONVERSATION_IDENTITY_CHANGED');
assert.equal(context.resolveRoutedTurn(record({beforeTurnKeys: ['old-turn']})).reason,
  'CONVERSATION_IDENTITY_CHANGED');
turns = [{key: 'turn-1', text: 'exact prompt'}, {key: 'turn-2', text: 'exact prompt'}];
assert.equal(context.resolveRoutedTurn(record()).reason, 'CONVERSATION_IDENTITY_CHANGED');
turns = [{key: 'turn-1', text: 'different prompt'}];
assert.equal(context.resolveRoutedTurn(record()).reason, 'CONVERSATION_IDENTITY_CHANGED');

console.log('Issue57 bootstrap identity rebind: pending route plus 5 fences PASS');
