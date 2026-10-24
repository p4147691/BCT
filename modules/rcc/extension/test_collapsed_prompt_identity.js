const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const RelayCore = require('./relay_core.js');
const content = fs.readFileSync('content/conversation_dom.js', 'utf8');
const background = fs.readFileSync('domain/diagnostic_support.js', 'utf8');

// Small tree/selector fixture, not a text-returning mock. Cloning, adjacency,
// descendants and removal all affect textContent like the observed DOM.
class Element {
  constructor(tag, attrs = {}, children = []) {
    this.tagName = tag; this.attrs = attrs; this.children = children;
    for (const child of children) if (child instanceof Element) child.parentElement = this;
  }
  get textContent() { return this.children.map(x => typeof x === 'string' ? x : x.textContent).join(''); }
  get innerText() { return this.textContent; }
  getAttribute(name) { return this.attrs[name] ?? null; }
  get previousElementSibling() {
    const siblings = this.parentElement?.children.filter(x => x instanceof Element) || [];
    return siblings[siblings.indexOf(this) - 1] || null;
  }
  matches(selectors) {
    return selectors.split(',').some(raw => {
      const selector = raw.trim();
      if (selector.includes(' + ')) {
        const [left, right] = selector.split(' + ');
        return this.matches(right) && !!this.previousElementSibling?.matches(left);
      }
      const tag = selector.match(/^[a-z]+/i)?.[0];
      if (tag && tag !== this.tagName) return false;
      if (selector.startsWith('.')) return (this.attrs.class || '').split(' ').includes(selector.slice(1));
      const attrs = [...selector.matchAll(/\[([^\]=~^$*]+)(?:([$^*]?=)"([^"]*)")?\]/g)];
      return !!(tag || attrs.length) && attrs.every(([, key, op, expected]) => {
        const actual = this.getAttribute(key);
        if (actual === null) return false;
        return !op || (op === '=' ? actual === expected : op === '$=' ? actual.endsWith(expected)
          : op === '^=' ? actual.startsWith(expected) : actual.includes(expected));
      });
    });
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => child instanceof Element
      ? [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)] : []);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
  contains(node) { return node === this || this.children.some(x => x instanceof Element && x.contains(node)); }
  cloneNode() { return new Element(this.tagName, {...this.attrs}, this.children.map(x => typeof x === 'string' ? x : x.cloneNode(true))); }
  remove() { this.parentElement.children = this.parentElement.children.filter(x => x !== this); }
  getClientRects() { return [{}]; }
}
const el = (tag, attrs, ...children) => new Element(tag, attrs, children);
function turn(key, prompt, options = {}) {
  // LIVE: full text stays inside overflow-hidden/data-search-result-target;
  // the hidden ellipsis is its sibling, outside the text body.
  const body = el('div', {'data-search-result-target': '', class: 'overflow-hidden'},
    el('div', {}, el('div', {class: 'text-size-chat whitespace-pre-wrap', dir: 'auto'}, prompt)));
  const decoration = el('span', {'aria-hidden': options.ariaHidden ?? 'true', class: 'block'}, options.decoration ?? '…');
  const semantic = el('div', {'data-content-search-unit-key': `${key}:user`},
    el('div', {}, body, ...(options.expanded ? [] : [decoration])),
    el('button', {'aria-expanded': String(!!options.expanded), 'data-markdown-copy': 'exclude'}, '더 보기'));
  if (options.insideText) body.children[0].children[0].children.push(el('span', {'aria-hidden': 'true'}, '…'));
  const user = el('div', {'data-message-author-role': 'user'}, semantic);
  return el('article', {'data-testid': `conversation-turn-${key}`},
    el('section', {'data-turn-key': key, 'data-talvt-turn-state': 'complete'}, user,
      el('div', {'data-message-author-role': 'assistant'}, '{"ok":true}'),
      el('button', {'data-testid': 'copy-turn-action-button'}, 'Copy')));
}
let document = el('main', {});
const context = vm.createContext({Element, RelayCore,
  newChatTextSha256: async value => require('node:crypto').createHash('sha256')
    .update(String(value), 'utf8').digest('hex'),
  currentConversationKey: () => 'conversation-test',
  getComputedStyle: () => ({visibility: 'visible', display: 'block'}),
  get document() { return document; }});
function slice(source, start, end) {
  const i = source.indexOf(start), j = source.indexOf(end, i);
  assert(i >= 0 && j > i, `missing source boundary ${start}`);
  return source.slice(i, j);
}
vm.runInContext(slice(content, 'function canonicalMessageUnit(', 'function getAssistantNodes(')
  + slice(content, 'function turnUserText(', 'function isVisible(')
  + ';globalThis.api={getConversationTurns,messageUnitText,turnUserText,resolveRoutedTurn,exactUserTurnsBySubmittedSha256};', context);
const directContext = vm.createContext({RelayCore, isChatTab: () => true,
  getComputedStyle: () => ({visibility: 'visible', display: 'block'}),
  get document() { return document; },
  browserGateway: {
    getExactTab: async () => ({url: 'https://chatgpt.com/c/conversation-test'}),
    executeScript: async spec => [{result: await spec.func(...spec.args)}],
  }});
vm.runInContext(slice(background, 'async function recoverCompletedReplyDirectlyFromTab(', 'function bindingLeaseTargetsConflict(')
  + ';globalThis.direct = recoverCompletedReplyDirectlyFromTab;', directContext);
const record = (prompt, extra = {}) => ({submittedText: prompt, conversationKey: 'conversation-test', beforeTurnKeys: [], ...extra});
const longPrompt = '[BCT_ORCHESTRATION_ASSIGNMENT_V1]\n' + 'bounded task '.repeat(95) + '\n[/BCT_ORCHESTRATION_ASSIGNMENT_V1]';

(async () => {
  let failures = 0;
  for (const [label, action] of [
    ['content real routed-turn entry', async () => {
      document = el('main', {}, turn('new', longPrompt));
      assert.equal(context.api.resolveRoutedTurn(record(longPrompt)).ok, true);
    }],
    ['background actual injected recovery function', async () => {
      document = el('main', {}, turn('new', longPrompt));
      assert.equal((await directContext.direct(901, 'conversation-test', longPrompt)).recoveredReply, '{"ok":true}');
    }]
  ]) {
    try { await action(); } catch (error) { failures++; console.error(label, error.message); }
  }
  assert.equal(failures, 0, 'both real extraction paths must ignore only the UI decoration');
  for (const prompt of [longPrompt, 'literal trailing …', '한글 😀\n  next line\n`inline code`', '<span aria-hidden="true">…</span>']) {
    for (const expanded of [false, true]) {
      document = el('main', {}, turn('new', prompt, {expanded}));
      const before = document.textContent;
      assert.equal(context.api.resolveRoutedTurn(record(prompt)).ok, true);
      assert.equal((await directContext.direct(901, 'conversation-test', prompt)).recovered, true);
      assert.equal(document.textContent, before, 'canonicalization must not mutate the live tree');
      assert.equal(context.api.resolveRoutedTurn(record(prompt + 'wrong')).ok, false);
    }
  }
  document = el('main', {}, turn('inline', 'Keep code and …'));
  assert.equal(context.api.resolveRoutedTurn(record('Keep `code` and …')).ok, true);
  assert.equal((await directContext.direct(901, 'conversation-test', 'Keep `code` and …')).recovered, true);
  for (const options of [{ariaHidden:'false'}, {decoration:'unexpected'}, {decoration:'...'}, {insideText:true}]) {
    document = el('main', {}, turn('new', longPrompt, options));
    assert.equal(context.api.resolveRoutedTurn(record(longPrompt)).ok, false, 'unknown/literal text is preserved');
    await assert.rejects(directContext.direct(901, 'conversation-test', longPrompt), /TURN_NOT_FOUND/);
  }
  document = el('main', {}, turn('a', longPrompt), turn('b', longPrompt));
  assert.equal(context.api.resolveRoutedTurn(record(longPrompt)).reason, 'ROUTE_TURN_AMBIGUOUS');
  const longPromptTurns = context.api.getConversationTurns();
  const longPromptHash = await context.newChatTextSha256(
    context.api.turnUserText(longPromptTurns[0]));
  assert.equal(longPromptTurns.length, 2);
  assert.equal(await context.newChatTextSha256(
    context.api.turnUserText(longPromptTurns[0])), longPromptHash);
  assert.equal((await context.api.exactUserTurnsBySubmittedSha256(longPromptHash)).length, 2,
    'hash-only reconciliation must retain the same uniqueness fence');
  await assert.rejects(directContext.direct(901, 'conversation-test', longPrompt), /TURN_AMBIGUOUS/);
  assert.equal(context.api.resolveRoutedTurn(record(longPrompt, {beforeTurnKeys:['a']})).turnKey, 'b');
  assert.equal(context.api.resolveRoutedTurn(record(longPrompt, {conversationKey:'wrong'})).reason, 'CONVERSATION_IDENTITY_CHANGED');
  document = el('main', {}, turn('wrong', 'different prompt'));
  assert.equal(context.api.resolveRoutedTurn(record(longPrompt, {routeTurnKey:'wrong'})).reason, 'ROUTE_TURN_USER_MISMATCH');
  await assert.rejects(directContext.direct(901, 'other-conversation', longPrompt), /IDENTITY_MISMATCH/);
  // The new user unit may be present before ChatGPT mounts a turn wrapper.
  const semanticOnly = (key, prompt) => el('div', {
    'data-content-search-unit-key': key + ':user'
  }, el('div', {'data-user-message-bubble': 'true'}, prompt));
  document = el('main', {}, semanticOnly('fresh', longPrompt));
  assert.equal(context.api.resolveRoutedTurn(record(longPrompt)).turnKey, 'fresh:user');
  assert.equal(context.api.resolveRoutedTurn(record(longPrompt + 'modified')).ok, false,
    'semantic fallback may not relax the exact user text check');
  document = el('main', {},
    semanticOnly('first', longPrompt), semanticOnly('second', longPrompt));
  assert.equal(context.api.resolveRoutedTurn(record(longPrompt)).reason, 'ROUTE_TURN_AMBIGUOUS',
    'distinct semantically keyed duplicate prompts fail closed');
  assert.equal(context.api.resolveRoutedTurn(
    record(longPrompt, {beforeTurnKeys: ['first:user']})).turnKey, 'second:user');
  document = el('main', {}, turn('legacy', longPrompt),
    semanticOnly('new', 'only second message'));
  assert.equal(context.api.resolveRoutedTurn(
    record('only second message', {beforeTurnKeys: ['legacy']})).turnKey, 'new:user');
  const secondHash = await context.newChatTextSha256('only second message');
  assert.equal((await context.api.exactUserTurnsBySubmittedSha256(secondHash))[0]
    .getAttribute('data-content-search-unit-key'), 'new:user');
  document = el('main', {}, el('div', {}, el('div', {
    'data-content-search-unit-key': 'wrong:assistant'
  }, longPrompt)));
  assert.equal(context.api.resolveRoutedTurn(record(longPrompt)).ok, false,
    'assistant semantic key is never treated as a user turn');
  console.log('collapsed prompt identity tests: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
