function renameUiError(code, effectState = 'NOT_APPLIED') {
  const error = new Error(String(code || 'RENAME_UI_FAILED'));
  error.effectState = effectState;
  return error;
}

function renameSleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForRenameUi(find, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = find();
    if (value) return value;
    await renameSleep(100);
  }
  return null;
}

function renameSemanticText(node) {
  return normalizedUiText([
    node?.getAttribute?.('aria-label'),
    node?.getAttribute?.('title'),
    node?.getAttribute?.('data-testid'),
    node?.textContent,
  ].filter(Boolean).join(' '));
}

function exactConversationAnchors(key) {
  return Array.from(document.querySelectorAll('a[href]')).filter((node) => {
    try {
      return new URL(node.href, location.href).pathname
        .match(/^\/c\/([a-z0-9-]{8,64})/i)?.[1] === key;
    } catch (_) {
      return false;
    }
  });
}

function visibleExactConversationAnchor(key) {
  const candidates = exactConversationAnchors(key).filter((node) => isVisible(node));
  const active = candidates.filter((node) =>
    node.getAttribute('aria-current') === 'page' ||
    node.getAttribute('data-active') === 'true' ||
    Boolean(node.closest?.('[aria-selected="true"], [data-state="active"], [data-active="true"]'))
  );
  return active[0] || candidates[0] || null;
}

function sidebarOpenButton() {
  return Array.from(document.querySelectorAll('button')).find((button) => {
    if (!isVisible(button) || button.disabled) return false;
    const text = renameSemanticText(button);
    return /(?:open|show|expand).*(?:sidebar)|(?:sidebar).*(?:open|show|expand)|사이드바.*(?:열기|펼치기|표시)/i.test(text);
  }) || null;
}

function activateRenameUiElement(element) {
  element.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  const common = { bubbles: true, cancelable: true, composed: true, view: window, button: 0 };
  if (typeof PointerEvent === 'function') {
    element.dispatchEvent(new PointerEvent('pointerdown', {
      ...common, pointerId: 1, pointerType: 'mouse', isPrimary: true, buttons: 1,
    }));
  }
  element.dispatchEvent(new MouseEvent('mousedown', { ...common, buttons: 1 }));
  if (typeof PointerEvent === 'function') {
    element.dispatchEvent(new PointerEvent('pointerup', {
      ...common, pointerId: 1, pointerType: 'mouse', isPrimary: true, buttons: 0,
    }));
  }
  element.dispatchEvent(new MouseEvent('mouseup', { ...common, buttons: 0 }));
  element.click();
}

async function ensureConversationAnchor(key) {
  let anchor = visibleExactConversationAnchor(key);
  if (anchor) return anchor;
  const open = sidebarOpenButton();
  if (open) activateRenameUiElement(open);
  anchor = await waitForRenameUi(() => visibleExactConversationAnchor(key), 3500);
  if (!anchor) throw renameUiError('RENAME_TARGET_NOT_FOUND');
  return anchor;
}

function conversationRow(anchor) {
  return anchor?.closest?.(
    '[data-sidebar-item="true"], [data-testid*="history-item"], nav li, aside li, li'
  ) || anchor?.parentElement || null;
}

function isConversationMenuButton(button) {
  const text = renameSemanticText(button);
  return /(?:chat|conversation).*(?:action|option|menu|more)|(?:more|option|menu).*(?:chat|conversation)|(?:대화|채팅).*(?:액션|옵션|메뉴|더 보기)/i.test(text) ||
    /^(more|more options|options|menu|더 보기|옵션|메뉴)$/i.test(text);
}

function rowMenuButton(anchor) {
  const row = conversationRow(anchor);
  const buttons = Array.from(row?.querySelectorAll?.('button') || [])
    .filter((button) => isVisible(button) && !button.disabled);
  const semantic = buttons.filter(isConversationMenuButton);
  if (semantic.length === 1) return semantic[0];
  const compact = buttons.filter((button) => {
    const rect = button.getBoundingClientRect();
    return rect.width <= 64 && rect.height <= 64 && Boolean(button.querySelector('svg'));
  });
  return semantic[0] || (compact.length === 1 ? compact[0] : null);
}

function currentConversationMenuButton() {
  const surface = document.querySelector(
    '[data-testid="app-shell-header-context-menu-surface"]'
  );
  if (!surface || !isVisible(surface)) return null;
  const buttons = Array.from(surface.querySelectorAll('button[aria-haspopup="menu"], button'))
    .filter((button) => isVisible(button) && !button.disabled);
  const matches = buttons.filter((button) => {
    const text = renameSemanticText(button);
    return /^(more|more options|options|menu|더보기|더 보기|옵션|메뉴)$/i.test(text);
  });
  return matches.length === 1 ? matches[0] : null;
}

function dispatchRenameHover(node) {
  const common = { bubbles: true, cancelable: true, composed: true, view: window };
  if (typeof PointerEvent === 'function') {
    node.dispatchEvent(new PointerEvent('pointerover', {
      ...common, pointerId: 1, pointerType: 'mouse', isPrimary: true,
    }));
  }
  node.dispatchEvent(new MouseEvent('mouseover', common));
  node.dispatchEvent(new MouseEvent('mousemove', common));
}

function visibleRenameMenuItems() {
  const roots = Array.from(document.querySelectorAll('[role="menu"], [data-radix-menu-content]'))
    .filter((node) => isVisible(node));
  const selector = '[role="menuitem"], button, a[href]';
  const items = roots.flatMap((root) => Array.from(root.querySelectorAll(selector)));
  if (!items.length) items.push(...document.querySelectorAll('[role="menuitem"]'));
  return [...new Set(items)].filter((node) => isVisible(node) && !node.disabled);
}

function findRenameMenuItem() {
  const matches = visibleRenameMenuItems().filter((node) => {
    const text = renameSemanticText(node);
    return /\brename\b|\bedit\s+(?:chat|conversation|title)\b|(?:이름|제목).*(?:바꾸기|변경|수정)|(?:바꾸기|변경|수정).*(?:이름|제목)/i.test(text);
  });
  if (matches.length === 1) return matches[0];
  const exact = matches.filter((node) =>
    /^(rename|rename chat|이름 바꾸기|이름 변경|제목 변경)$/i.test(normalizedUiText(node.textContent))
  );
  return exact.length === 1 ? exact[0] : null;
}

function openContextMenu(anchor) {
  const rect = anchor.getBoundingClientRect();
  const common = {
    bubbles: true, cancelable: true, composed: true, view: window,
    button: 2, buttons: 2,
    clientX: Math.max(1, Math.round(rect.left + Math.min(rect.width * 0.5, 120))),
    clientY: Math.max(1, Math.round(rect.top + rect.height * 0.5)),
  };
  if (typeof PointerEvent === 'function') {
    anchor.dispatchEvent(new PointerEvent('pointerdown', {
      ...common, pointerId: 1, pointerType: 'mouse', isPrimary: true,
    }));
  }
  anchor.dispatchEvent(new MouseEvent('mousedown', common));
  anchor.dispatchEvent(new MouseEvent('contextmenu', common));
  anchor.dispatchEvent(new MouseEvent('mouseup', { ...common, buttons: 0 }));
}

function isPromptComposerEditor(editor) {
  const semantic = renameSemanticText(editor);
  return /prompt|composer|message|메시지|프롬프트/i.test(semantic) ||
    Boolean(editor?.closest?.('[data-testid*="composer"], [class*="composer"]'));
}

function renameEditors() {
  const selector = 'input[type="text"], textarea, [contenteditable="true"], [role="textbox"]';
  return Array.from(document.querySelectorAll(selector)).filter((node) =>
    isVisible(node) && !node.disabled && !isPromptComposerEditor(node)
  );
}

function findRenameEditor(anchor) {
  const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).find(isVisible);
  const dialogEditors = dialog ? renameEditors().filter((node) => dialog.contains(node)) : [];
  if (dialogEditors.length === 1) return dialogEditors[0];
  const row = conversationRow(anchor);
  const rowEditors = row ? renameEditors().filter((node) => row.contains(node)) : [];
  if (rowEditors.length === 1) return rowEditors[0];
  const all = renameEditors();
  return all.length === 1 ? all[0] : null;
}

async function openConversationRenameEditor(key) {
  if (currentConversationKey() !== key) throw renameUiError('RENAME_TARGET_STALE');
  let anchor = visibleExactConversationAnchor(key);
  let menuButton = currentConversationMenuButton();
  if (!menuButton) {
    anchor = anchor || await ensureConversationAnchor(key);
    dispatchRenameHover(conversationRow(anchor) || anchor);
    menuButton = await waitForRenameUi(() => rowMenuButton(anchor), 1500);
  }
  if (menuButton) {
    activateRenameUiElement(menuButton);
  } else if (anchor) {
    openContextMenu(anchor);
  }
  let renameItem = await waitForRenameUi(findRenameMenuItem, 2500);
  if (!renameItem && anchor) {
    openContextMenu(anchor);
    renameItem = await waitForRenameUi(findRenameMenuItem, 2000);
  }
  if (!renameItem) throw renameUiError('RENAME_ACTION_NOT_FOUND');
  if (currentConversationKey() !== key) throw renameUiError('RENAME_TARGET_STALE');
  activateRenameUiElement(renameItem);
  const input = await waitForRenameUi(() => findRenameEditor(anchor), 5000);
  if (!input) throw renameUiError('RENAME_INPUT_NOT_FOUND');
  return { anchor, input };
}

function setRenameEditorValue(input, title) {
  input.focus();
  if (input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement) {
    const proto = input instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(input, title); else input.value = title;
  } else {
    input.textContent = title;
  }
  input.dispatchEvent(new InputEvent('input', {
    bubbles: true, inputType: 'insertText', data: title,
  }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

function currentTitleMatches(key, title) {
  const documentTitle = normalizedUiText(String(document.title || '')
    .replace(/\s*(?:[-–—|·]\s*)?ChatGPT\s*$/i, ''));
  if (documentTitle === title) return true;
  return exactConversationAnchors(key).some((anchor) =>
    normalizedUiText(anchor.textContent) === title ||
    normalizedUiText(anchor.getAttribute('aria-label')).startsWith(title)
  );
}

async function renameConversationUi(message) {
  const key = String(message.conversationKey || '').trim();
  const operationId = String(message.operationId || '').trim();
  const title = normalizedUiText(message.title);
  if (!key || currentConversationKey() !== key) throw renameUiError('RENAME_TARGET_STALE');
  if (!operationId || !title || title.length > 100) throw renameUiError('RENAME_INPUT_INVALID');

  const { input } = await openConversationRenameEditor(key);
  setRenameEditorValue(input, title);
  const scope = input.closest?.('[role="dialog"]') || input.closest?.('form') || input.parentElement;
  const form = input.closest?.('form');
  const save = Array.from(scope?.querySelectorAll?.('button') || []).find((button) => {
    if (!isVisible(button) || button.disabled) return false;
    const text = renameSemanticText(button);
    return /^(save|저장|confirm|확인)$/i.test(text) || button.type === 'submit';
  });
  if (currentConversationKey() !== key) throw renameUiError('RENAME_TARGET_STALE');
  await renameSleep(80);

  let effectStarted = false;
  try {
    effectStarted = true;
    if (form?.requestSubmit) form.requestSubmit(save?.type === 'submit' ? save : undefined);
    else if (save) activateRenameUiElement(save);
    else input.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter', code: 'Enter', bubbles: true, cancelable: true,
    }));

    const accepted = await waitForRenameUi(() =>
      (!document.contains(input) || !isVisible(input)) && currentTitleMatches(key, title), 8000
    );
    if (!accepted) throw renameUiError('RENAME_UI_NOT_VERIFIED', 'UNKNOWN');
    if (currentConversationKey() !== key) throw renameUiError('RENAME_TARGET_STALE_AFTER_SAVE', 'UNKNOWN');
    return { ok: true, effectState: 'APPLIED', operationId, savedTitle: title };
  } catch (error) {
    if (error?.effectState) throw error;
    throw renameUiError(error?.message || error, effectStarted ? 'UNKNOWN' : 'NOT_APPLIED');
  }
}
