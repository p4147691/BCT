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
const menuRoot = visibleNode();
menuRoot.querySelectorAll = (selector) =>
  selector === '[role="menuitem"], button, a[href]' ? [renameItem] : [];

const toolbarButton = visibleNode({
  'aria-label': '더보기',
  'aria-haspopup': 'menu',
});
const toolbar = visibleNode({
  'data-testid': 'app-shell-header-context-menu-surface',
});
toolbar.querySelectorAll = (selector) =>
  selector === 'button[aria-haspopup="menu"], button' ? [toolbarButton] : [];

const document = {
  querySelector: (selector) =>
    selector === '[data-testid="app-shell-header-context-menu-surface"]' ? toolbar : null,
  querySelectorAll: (selector) => {
    if (selector === '[role="menu"], [data-radix-menu-content]') return [menuRoot];
    if (selector === '[role="menuitem"]') return [renameItem];
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

console.log('conversation rename UI v2: PASS');
