const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('content.js', 'utf8');
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

assert.equal(context.resolveRoutedTurn(record({bootstrapCreatedTab: false})).reason,
  'CONVERSATION_IDENTITY_CHANGED');
assert.equal(context.resolveRoutedTurn(record({beforeTurnKeys: ['old-turn']})).reason,
  'CONVERSATION_IDENTITY_CHANGED');
turns = [{key: 'turn-1', text: 'exact prompt'}, {key: 'turn-2', text: 'exact prompt'}];
assert.equal(context.resolveRoutedTurn(record()).reason, 'CONVERSATION_IDENTITY_CHANGED');
turns = [{key: 'turn-1', text: 'different prompt'}];
assert.equal(context.resolveRoutedTurn(record()).reason, 'CONVERSATION_IDENTITY_CHANGED');

console.log('Issue57 bootstrap identity rebind: 5 fences PASS');
