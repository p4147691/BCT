const assert = require('assert');
const fs = require('fs');

const source = fs.readFileSync('content/conversation_dom.js', 'utf8');
const messageBegin = source.indexOf('function canonicalMessageUnit(');
const messageEnd = source.indexOf('function messageUnitRole(', messageBegin);
assert(messageBegin >= 0 && messageEnd > messageBegin);
const begin = source.indexOf('function getConversationTurns()');
const end = source.indexOf('function turnIdentity(', begin);
assert(begin >= 0 && end > begin);

class FakeElement {
  constructor(kind, child = null) {
    this.kind = kind;
    this.child = child;
  }
  matches(selector) {
    return selector === '[data-turn-key]' && this.kind === 'turn-key';
  }
  closest(selector) {
    return selector === '[data-turn-key]' && this.kind === 'turn-key' ? this : null;
  }
  querySelectorAll(selector) {
    return selector === '[data-turn-key]' && this.child ? [this.child] : [];
  }
}

const logicalTurn = new FakeElement('turn-key');
const compatibilityWrapper = new FakeElement('conversation-testid', logicalTurn);
const document = {
  querySelectorAll() {
    // This is the exact shape observed in LIVE diagnostics: two nested DOM
    // wrappers expose the same user/assistant turn.
    return [compatibilityWrapper, logicalTurn];
  }
};
const getConversationTurns = new Function(
  'document', 'Element',
  source.slice(begin, end) + '\nreturn getConversationTurns;'
)(document, FakeElement);

const turns = getConversationTurns();
assert.strictEqual(turns.length, 1, 'nested wrappers must resolve to one logical turn');
assert.strictEqual(turns[0], logicalTurn, 'data-turn-key is the canonical routed turn');

class FakeMessageElement {
  constructor(kind, child = null) {
    this.kind = kind;
    this.child = child;
  }
  matches(selector) {
    if (selector === '[data-message-author-role="user"]') return this.kind === 'legacy-user';
    if (selector === '[data-content-search-unit-key]') return this.kind === 'semantic-user';
    return false;
  }
  closest(selector) {
    if (selector === '[data-content-search-unit-key]') {
      return this.kind === 'semantic-user' ? this : null;
    }
    if (selector === '[data-user-message-bubble="true"]') return null;
    return null;
  }
  querySelectorAll(selector) {
    if (this.kind === 'legacy-user' && selector.includes('data-content-search-unit-key')) {
      return [this.child];
    }
    return [];
  }
}
const semanticUser = new FakeMessageElement('semantic-user');
const legacyUserWrapper = new FakeMessageElement('legacy-user', semanticUser);
const canonicalMessageUnit = new Function(
  'Element', source.slice(messageBegin, messageEnd) + '\nreturn canonicalMessageUnit;'
)(FakeMessageElement);
assert.strictEqual(
  canonicalMessageUnit(legacyUserWrapper, 'user'), semanticUser,
  'nested legacy and semantic wrappers must resolve to one semantic message unit'
);
console.log('route turn deduplication tests: PASS');
