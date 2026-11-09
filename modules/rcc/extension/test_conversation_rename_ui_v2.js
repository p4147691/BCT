const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/content/conversation_rename.js`, 'utf8');

function visibleNode(attributes = {}, textContent = '') {
  return {
    disabled: false,
    textContent,
    getAttribute: (name) => attributes[name] ?? null,
    getClientRects: () => [{}],
  };
}

const renameItem = visibleNode({}, '이름 변경');
const renameInput = visibleNode({
  'aria-label': '채팅 제목',
  placeholder: '제목 추가…',
});
const dialog = visibleNode();
dialog.contains = (node) => node === renameInput;
const menuRoot = visibleNode();
menuRoot.querySelectorAll = (selector) =>
  selector === '[role="menuitem"], button, a[href]' ? [renameItem] : [];

const toolbarButton = visibleNode({
  'aria-label': 'Chat actions',
  'aria-haspopup': 'menu',
});
const toolbar = visibleNode({
  'data-testid': 'app-shell-header-context-menu-surface',
});
toolbar.querySelectorAll = (selector) =>
  selector === 'button[aria-haspopup="menu"], button' ? [toolbarButton] : [];

const document = {
  title: '전역 Supervisor 대기確認 - ChatGPT',
  querySelector: (selector) =>
    selector === '[data-testid="app-shell-header-context-menu-surface"]' ? toolbar : null,
  querySelectorAll: (selector) => {
    if (selector === '[role="menu"], [data-radix-menu-content]') return [menuRoot];
    if (selector === '[role="menuitem"]') return [renameItem];
    if (selector === '[role="dialog"]') return [dialog];
    if (selector === 'input:not([type]), input[type="text"], textarea, [contenteditable="true"], [role="textbox"]') {
      return [renameInput];
    }
    return [];
  },
};

const context = vm.createContext({
  document,
  window: {},
  location: { href: 'https://chatgpt.com/c/exact-key', pathname: '/c/exact-key' },
  URL,
  setTimeout,
  clearTimeout,
  normalizedUiText: (value) => String(value || '').trim().replace(/\s+/g, ' '),
  isVisible: (node) => Boolean(node?.getClientRects?.().length),
  currentConversationKey: () => 'exact-key',
  MouseEvent: class {},
  PointerEvent: class {},
  InputEvent: class {},
  Event: class {},
  KeyboardEvent: class {},
  HTMLInputElement: class {},
  HTMLTextAreaElement: class {},
});

vm.runInContext(source, context, { filename: 'conversation_rename.js' });

assert.equal(
  vm.runInContext('currentConversationMenuButton()', context),
  toolbarButton,
  'collapsed sidebar must use the exact current-conversation toolbar menu'
);
assert.equal(
  vm.runInContext('findRenameMenuItem()', context),
  renameItem,
  'the current Korean label "이름 변경" must be recognized'
);
assert.equal(
  vm.runInContext('findRenameEditor(null)', context),
  renameInput,
  'a rename dialog input with the implicit default text type must be recognized'
);

const titlePopup = visibleNode({ 'aria-haspopup': 'menu' }, '전역 Supervisor 대기確認');
document.querySelector = () => null;
document.querySelectorAll = (selector) =>
  selector === 'button[aria-haspopup="menu"]' ? [titlePopup] : [];
assert.equal(
  vm.runInContext('currentConversationMenuButton()', context),
  titlePopup,
  'the unique popup whose text is the exact document title must identify the current conversation without header markup'
);

const changedHeaderPopup = visibleNode({ 'aria-haspopup': 'menu' });
changedHeaderPopup.querySelectorAll = () => [];
const changedHeader = visibleNode();
changedHeader.querySelectorAll = (selector) => selector.includes('button') ? [changedHeaderPopup] : [];
document.querySelector = () => null;
document.querySelectorAll = (selector) => {
  if (selector.includes('main header')) return [changedHeader];
  return [];
};
assert.equal(
  vm.runInContext('currentConversationMenuButton()', context),
  changedHeaderPopup,
  'one icon-only aria-haspopup menu button in the bounded current-chat header must survive ChatGPT header markup drift'
);

const dotKey = 'b227a510-d0cb-4466-a2f5-4e401b456dca~6af1261141a8819aa57d94044451fee3';
const dotAnchor = visibleNode({ 'aria-current': 'page' }, '내 dot');
dotAnchor.href = `https://chatgpt.com/dots/${dotKey}`;
context.location.href = dotAnchor.href;
document.querySelectorAll = (selector) => selector === 'a[href]' ? [dotAnchor] : [];
assert.equal(vm.runInContext('dotKeyFromLocation()', context), dotKey,
  'the current Dot identity must be the full confirmed compound reference');
assert.equal(vm.runInContext(`exactDotAnchors('${dotKey}').length`, context), 1,
  'the sidebar target must match the entire Dot address rather than a UUID-like fragment');
assert.equal(vm.runInContext("exactDotAnchors('b227a510-d0cb-4466-a2f5-4e401b456dca~wrong').length", context), 0,
  'a different Dot context reference must not be accepted as the same target');

console.log('conversation rename UI v2: PASS');
