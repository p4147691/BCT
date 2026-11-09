function renameUiError(code, effectState = 'NOT_APPLIED', diagnostic = null) {
  const error = new Error(String(code || 'RENAME_UI_FAILED'));
  error.effectState = effectState;
  if (diagnostic) error.renameDiagnostic = { ...diagnostic };
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

function dotKeyFromLocation(value = location.href) {
  try {
    const url = new URL(String(value || ''), location.href);
    if (!/^(?:chatgpt\.com|chat\.openai\.com)$/i.test(url.hostname)) return '';
    return url.pathname.match(/^\/dots\/([A-Za-z0-9_-]{1,160}~[A-Za-z0-9_-]{1,160})\/?$/)?.[1] || '';
  } catch (_) {
    return '';
  }
}

function exactDotAnchors(key) {
  return Array.from(document.querySelectorAll('a[href]')).filter((node) => {
    try {
      return dotKeyFromLocation(new URL(node.href, location.href).href) === key;
    } catch (_) {
      return false;
    }
  });
}

function visibleExactDotAnchor(key) {
  const candidates = exactDotAnchors(key).filter((node) => isVisible(node));
  const active = candidates.filter((node) =>
    node.getAttribute('aria-current') === 'page' ||
    node.getAttribute('data-active') === 'true' ||
    Boolean(node.closest?.('[aria-selected="true"], [data-state="active"], [data-active="true"]'))
  );
  return active[0] || candidates[0] || null;
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

function sidebarHoverRevealControl() {
  // In the compact ChatGPT shell the full sidebar is a hover flyout from the
  // Home icon instead of a persistent panel with an "open sidebar" button.
  // Match only the visible Home control (including current Korean UI labels),
  // never an arbitrary navigation link.
  const controls = Array.from(document.querySelectorAll(
    'nav button, nav a[href], aside button, aside a[href], '
    + '[data-testid*="sidebar"] button, [data-testid*="sidebar"] a[href]'
  )).filter((node) => isVisible(node) && !node.disabled);
  const semantic = controls.filter((node) =>
    /^(?:home|홈|chatgpt home|chatgpt 홈)$/i.test(renameSemanticText(node))
  );
  if (semantic.length === 1) return semantic[0];
  const rootLinks = controls.filter((node) => {
    try {
      const url = new URL(String(node.href || node.getAttribute?.('href') || ''), location.href);
      return /^(?:chatgpt\.com|chat\.openai\.com)$/i.test(url.hostname) && url.pathname === '/';
    } catch (_) {
      return false;
    }
  });
  return rootLinks.length === 1 ? rootLinks[0] : null;
}

function currentDotDisplayTitle() {
  return normalizedUiText(String(document.title || '')
    .replace(/\s*(?:[-–—|·]\s*)?ChatGPT\s*$/i, ''));
}

function dotProfileTitleControl() {
  const title = currentDotDisplayTitle();
  if (!title) return null;
  // The current Dot profile card exposes its title above the Active status.
  // Prefer that bounded main-content control; the compact sidebar remains a
  // separate fallback because its flyout markup changes more frequently.
  const controls = Array.from(document.querySelectorAll(
    'main button, main [role="button"], main [tabindex="0"], '
    + '[data-testid*="dot"] button, [data-testid*="dot"] [role="button"]'
  )).filter((node) => isVisible(node) && !node.disabled &&
    !node.closest?.('nav, [data-testid*="sidebar"]'));
  const exact = controls.filter((node) => renameSemanticText(node) === title);
  if (exact.length === 1) return exact[0];
  // Some ChatGPT builds attach the click handler to an unlabelled profile
  // container while rendering the title as a plain heading/span.  Clicking
  // the unique exact title leaf still bubbles through that handler.
  const leaves = Array.from(document.querySelectorAll('main *'))
    .filter((node) => isVisible(node) && !node.closest?.('nav, [data-testid*="sidebar"]'))
    .filter((node) => normalizedUiText(node.textContent) === title)
    .filter((node) => !Array.from(node.children || []).some((child) =>
      normalizedUiText(child.textContent) === title
    ));
  if (leaves.length === 1) return leaves[0];
  // The Dot profile pane is not consistently wrapped in <main>.  Bound the
  // fallback by the adjacent Active/활성 state instead of a CSS class or
  // screen coordinate, then click the exact current-name leaf so the site's
  // own React handler opens the customizer.
  const allLeaves = Array.from(document.querySelectorAll('*'))
    .filter((node) => isVisible(node) && !node.closest?.('nav, [data-testid*="sidebar"]'))
    .filter((node) => normalizedUiText(node.textContent) === title)
    .filter((node) => !Array.from(node.children || []).some((child) =>
      normalizedUiText(child.textContent) === title
    ));
  const profileLeaves = allLeaves.filter((leaf) => {
    let scope = leaf.parentElement;
    for (let depth = 0; scope && depth < 7; depth += 1, scope = scope.parentElement) {
      if (/(?:^|\s)(?:active|활성)(?:\s|$)/i.test(renameSemanticText(scope))) return true;
    }
    return false;
  });
  return profileLeaves.length === 1 ? profileLeaves[0] : null;
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

async function ensureDotAnchor(key) {
  let anchor = visibleExactDotAnchor(key);
  if (anchor) return anchor;
  const hoverReveal = sidebarHoverRevealControl();
  if (hoverReveal) {
    dispatchRenameHover(hoverReveal);
    anchor = await waitForRenameUi(() => visibleExactDotAnchor(key), 2500);
    if (anchor) return anchor;
  }
  const open = sidebarOpenButton();
  if (open) activateRenameUiElement(open);
  anchor = await waitForRenameUi(() => visibleExactDotAnchor(key), 3500);
  if (!anchor) throw renameUiError('DOT_RENAME_TARGET_NOT_FOUND');
  return anchor;
}

function conversationRow(anchor) {
  const semanticRow = anchor?.closest?.(
    '[data-sidebar-item="true"], [data-testid*="history-item"], nav li, aside li, li'
  );
  if (semanticRow) return semanticRow;
  const candidates = conversationRowCandidates(anchor);
  return candidates.find((node) => node.querySelectorAll?.('button')?.length) ||
    candidates[0] || null;
}

function conversationRowCandidates(anchor) {
  const candidates = [];
  let node = anchor?.parentElement || null;
  for (let depth = 0; node && depth < 7; depth += 1, node = node.parentElement) {
    candidates.push(node);
    if (/^(?:NAV|ASIDE)$/i.test(String(node.tagName || ''))) break;
  }
  return candidates;
}

function isRenderedRenameControl(node) {
  // Sidebar action buttons are commonly opacity-hidden until a real :hover.
  // They remain bounded to the exact target row and are safe to click when
  // they still have layout boxes; do not widen this to arbitrary page buttons.
  return Boolean(node?.getClientRects?.().length) && !node.disabled;
}

function isConversationMenuButton(button) {
  const text = renameSemanticText(button);
  return /(?:chat|conversation).*(?:action|option|menu|more)|(?:more|option|menu).*(?:chat|conversation)|(?:대화|채팅).*(?:액션|옵션|메뉴|더 보기)/i.test(text) ||
    /^(more|more options|options|menu|더 보기|옵션|메뉴)$/i.test(text);
}

function rowMenuButton(anchor) {
  const rows = [...new Set([conversationRow(anchor), ...conversationRowCandidates(anchor)])]
    .filter(Boolean);
  for (const row of rows) {
    const buttons = Array.from(row.querySelectorAll?.('button') || [])
      .filter(isRenderedRenameControl);
    const popup = buttons.filter((button) =>
      /menu/i.test(String(button.getAttribute?.('aria-haspopup') || ''))
    );
    if (popup.length === 1) return popup[0];
    const semantic = buttons.filter(isConversationMenuButton);
    if (semantic.length === 1) return semantic[0];
    const compact = buttons.filter((button) => {
      const rect = button.getBoundingClientRect();
      return rect.width <= 64 && rect.height <= 64 && Boolean(button.querySelector('svg'));
    });
    if (semantic[0] || compact.length === 1) return semantic[0] || compact[0];
  }
  return null;
}

function currentConversationMenuButton() {
  const currentTitle = normalizedUiText(String(document.title || '')
    .replace(/\s*(?:[-–—|·]\s*)?ChatGPT\s*$/i, ''));
  if (currentTitle) {
    const titlePopups = Array.from(document.querySelectorAll('button[aria-haspopup="menu"]'))
      .filter((button) => isVisible(button) && !button.disabled)
      .filter((button) => normalizedUiText(button.textContent) === currentTitle);
    if (titlePopups.length === 1) return titlePopups[0];
  }
  // ChatGPT has moved the current-chat menu between a dedicated test-id
  // surface, a semantic header and the title toolbar.  Search only those
  // bounded header surfaces; never select an arbitrary page/menu button.
  const surfaceSelector = [
    '[data-testid="app-shell-header-context-menu-surface"]',
    '[data-testid*="app-shell-header"]',
    '[data-testid*="conversation-header"]',
    '[data-testid*="chat-header"]',
    'main header',
    'header',
  ].join(',');
  const surfaces = Array.from(document.querySelectorAll(surfaceSelector));
  // Retain compatibility with the older dedicated surface and with small
  // test/embedded DOM adapters that expose only querySelector.
  const dedicated = document.querySelector?.(
    '[data-testid="app-shell-header-context-menu-surface"]'
  );
  if (dedicated && !surfaces.includes(dedicated)) surfaces.push(dedicated);
  const visibleSurfaces = surfaces.filter((node) => isVisible(node));
  const buttons = [...new Set(visibleSurfaces.flatMap((surface) =>
    Array.from(surface.querySelectorAll('button[aria-haspopup="menu"], button'))
  ))]
    .filter((button) => isVisible(button) && !button.disabled);
  const matches = buttons.filter((button) => {
    const text = renameSemanticText(button);
    return /^(more|more options|options|menu|chat actions?|더보기|더 보기|옵션|메뉴|채팅 작업|대화 작업)$/i.test(text);
  });
  if (matches.length === 1) return matches[0];
  // The current UI can render the title chevron as an icon-only popup button.
  // Accept it only when exactly one visible menu-popup button exists across
  // the bounded header surfaces.
  const popup = buttons.filter((button) =>
    /menu/i.test(String(button.getAttribute?.('aria-haspopup') || ''))
  );
  return popup.length === 1 ? popup[0] : null;
}

function dispatchRenameHover(node) {
  const common = { bubbles: true, cancelable: true, composed: true, view: window };
  node.focus?.({ preventScroll: true });
  if (typeof PointerEvent === 'function') {
    node.dispatchEvent(new PointerEvent('pointerenter', {
      ...common, pointerId: 1, pointerType: 'mouse', isPrimary: true,
    }));
    node.dispatchEvent(new PointerEvent('pointerover', {
      ...common, pointerId: 1, pointerType: 'mouse', isPrimary: true,
    }));
  }
  node.dispatchEvent(new MouseEvent('mouseenter', common));
  node.dispatchEvent(new MouseEvent('mouseover', common));
  node.dispatchEvent(new MouseEvent('mousemove', common));
  if (typeof FocusEvent === 'function') {
    node.dispatchEvent(new FocusEvent('focusin', common));
  }
}

function visibleRenameMenuItems() {
  // ChatGPT has used both Radix menu content and a portalled popover wrapper
  // for this control.  Keep the search constrained to visible menu/popover
  // surfaces so an unrelated page button cannot become a rename candidate.
  const roots = Array.from(document.querySelectorAll(
    '[role="menu"], [data-radix-menu-content], [data-radix-popper-content-wrapper], '
    + '[data-radix-menu-portal], [data-slot="dropdown-menu-content"], '
    + '[data-testid*="menu"], [data-testid*="popover"]'
  ))
    .filter((node) => isVisible(node));
  const selector = '[role^="menuitem"], button, a[href], [data-testid]';
  const items = roots.flatMap((root) => Array.from(root.querySelectorAll(selector)));
  if (!items.length) items.push(...document.querySelectorAll('[role="menuitem"]'));
  return [...new Set(items)].filter((node) => isVisible(node) && !node.disabled);
}

function findRenameMenuItem() {
  const matches = visibleRenameMenuItems().filter((node) => {
    const text = renameSemanticText(node);
    return /\brename\b|\b(?:edit|change)\s+(?:chat|conversation|title|display)\b|(?:이름|제목).*(?:바꾸기|변경|수정|편집)|(?:바꾸기|변경|수정|편집).*(?:이름|제목)/i.test(text);
  });
  if (matches.length === 1) return matches[0];
  const exact = matches.filter((node) =>
    /^(rename|rename chat|edit title|change display title|이름 바꾸기|이름 변경|이름 편집|제목 변경|제목 편집)$/i.test(normalizedUiText(node.textContent))
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
  // ChatGPT's current rename dialog uses an <input> without an explicit
  // type attribute (the HTML default is still text).  Requiring
  // input[type="text"] therefore skipped the only dialog editor after the
  // rename action had already opened it.
  const selector = 'input:not([type]), input[type="text"], textarea, [contenteditable="true"], [role="textbox"]';
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

function visibleDotCustomizationDialog() {
  const title = currentDotDisplayTitle();
  if (!title) return null;
  const hasExactTitle = (scope) =>
    Array.from(scope.querySelectorAll?.('*') || []).some((node) =>
      isVisible(node) && normalizedUiText(node.textContent) === title
    );
  const hasSave = (scope) => Array.from(scope.querySelectorAll?.('button') || [])
    .some((button) => isVisible(button) && /^(?:save|저장)$/i.test(renameSemanticText(button)));
  const explicit = Array.from(document.querySelectorAll(
    '[role="dialog"], [aria-modal="true"], [data-radix-dialog-content]'
  )).filter((scope) => isVisible(scope) && hasExactTitle(scope) && hasSave(scope));
  if (explicit.length === 1) return explicit[0];

  // Current ChatGPT Dot customizer builds have shipped without role=dialog.
  // Recover the smallest visible ancestor that contains both the exact current
  // Dot name and the site's Save control.  This remains semantic and bounded:
  // body/documentElement are never accepted and no page text is returned.
  const leaves = Array.from(document.querySelectorAll('*'))
    .filter((node) => isVisible(node) && normalizedUiText(node.textContent) === title)
    .filter((node) => !Array.from(node.children || []).some((child) =>
      normalizedUiText(child.textContent) === title
    ));
  const scopes = [];
  for (const leaf of leaves) {
    let scope = leaf.parentElement;
    for (let depth = 0; scope && depth < 12; depth += 1, scope = scope.parentElement) {
      if (scope === document.body || scope === document.documentElement) break;
      if (isVisible(scope) && hasSave(scope)) {
        scopes.push(scope);
        break;
      }
    }
  }
  return scopes.length === 1 ? scopes[0] : null;
}

function dotCustomizationNameControl(dialog) {
  if (!dialog || !isVisible(dialog)) return null;
  const title = currentDotDisplayTitle();
  if (!title) return null;
  const controls = Array.from(dialog.querySelectorAll?.(
    'button, [role="button"], [tabindex="0"]'
  ) || []).filter((node) => isVisible(node) && !node.disabled);
  const exactControls = controls.filter((node) => renameSemanticText(node) === title);
  if (exactControls.length === 1) return exactControls[0];
  // The current Dot customizer renders the name as plain text inside a
  // clickable React container.  Clicking the unique exact leaf bubbles to the
  // container and opens the actual name editor without depending on CSS names.
  const leaves = Array.from(dialog.querySelectorAll?.('*') || [])
    .filter((node) => isVisible(node) && normalizedUiText(node.textContent) === title)
    .filter((node) => !Array.from(node.children || []).some((child) =>
      normalizedUiText(child.textContent) === title
    ));
  return leaves.length === 1 ? leaves[0] : null;
}

function findDotProfileRenameEditor(dialog = visibleDotCustomizationDialog()) {
  if (!dialog) return null;
  const editors = renameEditors().filter((node) => dialog.contains(node));
  const named = editors.filter((node) =>
    /name|title|이름|제목/i.test(renameSemanticText(node))
  );
  if (named.length === 1) return named[0];
  return editors.length === 1 ? editors[0] : null;
}

async function openConversationRenameEditor(key) {
  // Diagnostic values are fixed stage/status flags, never DOM contents.
  const diagnostic = {
    version: 1, identity: 'MATCH', menuButton: 'NOT_FOUND',
    menuClick: 'NOT_ATTEMPTED', menuVisible: 'NOT_OBSERVED',
    renameAction: 'NOT_FOUND', editor: 'NOT_CHECKED',
  };
  if (currentConversationKey() !== key) {
    diagnostic.identity = 'MISMATCH';
    throw renameUiError('RENAME_TARGET_STALE', 'NOT_APPLIED', diagnostic);
  }
  let anchor = visibleExactConversationAnchor(key);
  let menuButton = currentConversationMenuButton();
  if (!menuButton) {
    anchor = anchor || await ensureConversationAnchor(key);
    dispatchRenameHover(conversationRow(anchor) || anchor);
    menuButton = await waitForRenameUi(() => rowMenuButton(anchor), 1500);
  }
  if (menuButton) {
    diagnostic.menuButton = 'FOUND';
    diagnostic.menuClick = 'ATTEMPTED';
    activateRenameUiElement(menuButton);
  } else if (anchor) {
    diagnostic.menuClick = 'CONTEXT_MENU_ATTEMPTED';
    openContextMenu(anchor);
  }
  // Observe only the existence of a menu, never its labels or inner HTML.
  const visibleMenu = () => Array.from(
    document.querySelectorAll('[role="menu"], [data-radix-menu-content]')
  ).some(isVisible);
  let renameItem = await waitForRenameUi(() => {
    if (visibleMenu()) diagnostic.menuVisible = 'OBSERVED';
    return findRenameMenuItem();
  }, 2500);
  if (!renameItem && anchor) {
    diagnostic.menuClick = 'CONTEXT_MENU_ATTEMPTED';
    openContextMenu(anchor);
    renameItem = await waitForRenameUi(() => {
      if (visibleMenu()) diagnostic.menuVisible = 'OBSERVED';
      return findRenameMenuItem();
    }, 2000);
  }
  if (!renameItem) throw renameUiError('RENAME_ACTION_NOT_FOUND', 'NOT_APPLIED', diagnostic);
  diagnostic.renameAction = 'FOUND';
  if (currentConversationKey() !== key) {
    diagnostic.identity = 'MISMATCH';
    throw renameUiError('RENAME_TARGET_STALE', 'NOT_APPLIED', diagnostic);
  }
  activateRenameUiElement(renameItem);
  const input = await waitForRenameUi(() => findRenameEditor(anchor), 5000);
  if (!input) {
    diagnostic.editor = 'NOT_FOUND';
    throw renameUiError('RENAME_INPUT_NOT_FOUND', 'NOT_APPLIED', diagnostic);
  }
  diagnostic.editor = 'FOUND';
  return { anchor, input, diagnostic };
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

function enabledRenameSaveControl(scope) {
  const buttons = Array.from(scope?.querySelectorAll?.('button') || []);
  return buttons.find((button) => {
    if (!isVisible(button) || button.disabled) return false;
    const text = renameSemanticText(button);
    return /^(save|저장|confirm|확인)$/i.test(text) || button.type === 'submit';
  }) || null;
}

function renameSubmitScope(input, scopeHint = null) {
  const hasSave = (scope) => Array.from(scope?.querySelectorAll?.('button') || [])
    .some((button) => /^(save|저장|confirm|확인)$/i.test(renameSemanticText(button))
      || button.type === 'submit');
  let scope = input.closest?.('[role="dialog"], [aria-modal="true"], [data-radix-dialog-content]')
    || input.closest?.('form');
  if (scope && hasSave(scope)) return scope;
  scope = input.parentElement;
  for (let depth = 0; scope && depth < 12; depth += 1, scope = scope.parentElement) {
    if (scope === document.body || scope === document.documentElement) break;
    if (hasSave(scope)) return scope;
  }
  if (scopeHint && scopeHint.contains?.(input) && hasSave(scopeHint)) return scopeHint;
  return input.closest?.('form') || input.parentElement;
}

async function submitRenameEditor(input, scopeHint = null) {
  const scope = renameSubmitScope(input, scopeHint);
  const form = input.closest?.('form');
  // React enables the dialog's Save button on a later render after the input
  // event.  Submitting the form immediately can bypass the actual onClick
  // handler while the visible Save button is still disabled.
  const save = await waitForRenameUi(() => enabledRenameSaveControl(scope), 1500);
  if (save) {
    activateRenameUiElement(save);
    return 'SAVE_BUTTON';
  }
  if (form?.requestSubmit) {
    form.requestSubmit();
    return 'FORM_SUBMIT';
  }
  input.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter', code: 'Enter', bubbles: true, cancelable: true,
  }));
  return 'ENTER';
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
  if (currentConversationKey() !== key) throw renameUiError('RENAME_TARGET_STALE');
  await renameSleep(80);

  let effectStarted = false;
  try {
    effectStarted = true;
    await submitRenameEditor(input);

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

function currentDotTitleMatches(key, title) {
  const documentTitle = normalizedUiText(String(document.title || '')
    .replace(/\s*(?:[-–—|·]\s*)?ChatGPT\s*$/i, ''));
  if (documentTitle === title) return true;
  return exactDotAnchors(key).some((anchor) =>
    normalizedUiText(anchor.textContent) === title ||
    normalizedUiText(anchor.getAttribute('aria-label')).startsWith(title)
  );
}

async function openDotRenameEditor(key) {
  const diagnostic = {
    version: 4, identity: 'MATCH', menuButton: 'NOT_FOUND', menuClick: 'NOT_ATTEMPTED',
    menuVisible: 'NOT_OBSERVED', renameAction: 'NOT_FOUND', editor: 'NOT_CHECKED',
    customizeDialog: 'NOT_OBSERVED', customizeName: 'NOT_ATTEMPTED',
  };
  if (dotKeyFromLocation() !== key) {
    diagnostic.identity = 'MISMATCH';
    throw renameUiError('DOT_RENAME_TARGET_STALE', 'NOT_APPLIED', diagnostic);
  }
  let customizeDialog = visibleDotCustomizationDialog();
  const profileTitle = customizeDialog ? null : dotProfileTitleControl();
  if (customizeDialog || profileTitle) {
    if (!customizeDialog) {
      diagnostic.menuClick = 'PROFILE_TITLE_ATTEMPTED';
      activateRenameUiElement(profileTitle);
      customizeDialog = await waitForRenameUi(() => visibleDotCustomizationDialog(), 5000);
    }
    if (!customizeDialog) {
      throw renameUiError('DOT_CUSTOMIZATION_DIALOG_NOT_FOUND', 'NOT_APPLIED', diagnostic);
    }
    diagnostic.customizeDialog = 'OBSERVED';
    let profileInput = findDotProfileRenameEditor(customizeDialog);
    if (!profileInput) {
      const nameControl = dotCustomizationNameControl(customizeDialog);
      if (!nameControl) {
        throw renameUiError('DOT_CUSTOMIZATION_NAME_CONTROL_NOT_FOUND', 'NOT_APPLIED', diagnostic);
      }
      if (dotKeyFromLocation() !== key) {
        diagnostic.identity = 'MISMATCH';
        throw renameUiError('DOT_RENAME_TARGET_STALE', 'NOT_APPLIED', diagnostic);
      }
      diagnostic.customizeName = 'ATTEMPTED';
      activateRenameUiElement(nameControl);
      profileInput = await waitForRenameUi(
        () => findDotProfileRenameEditor(customizeDialog), 5000
      );
    }
    if (profileInput) {
      diagnostic.renameAction = 'CUSTOMIZATION_NAME';
      diagnostic.editor = 'FOUND';
      return { input: profileInput, scope: customizeDialog, diagnostic };
    }
    throw renameUiError('DOT_PROFILE_RENAME_INPUT_NOT_FOUND', 'NOT_APPLIED', diagnostic);
  }
  const anchor = await ensureDotAnchor(key);
  const row = conversationRow(anchor) || anchor;
  dispatchRenameHover(row);
  let menuButton = await waitForRenameUi(() => rowMenuButton(anchor), 1500);
  if (menuButton) {
    diagnostic.menuButton = 'FOUND';
    diagnostic.menuClick = 'BUTTON_ATTEMPTED';
    activateRenameUiElement(menuButton);
  } else {
    diagnostic.menuClick = 'CONTEXT_MENU_ATTEMPTED';
    openContextMenu(row);
  }
  const visibleMenu = () => Array.from(
    document.querySelectorAll('[role="menu"], [data-radix-menu-content]')
  ).some(isVisible);
  let renameItem = await waitForRenameUi(() => {
    if (visibleMenu()) diagnostic.menuVisible = 'OBSERVED';
    return findRenameMenuItem();
  }, 2500);
  if (!renameItem && menuButton) {
    diagnostic.menuClick = 'CONTEXT_MENU_ATTEMPTED';
    openContextMenu(row);
    renameItem = await waitForRenameUi(() => {
      if (visibleMenu()) diagnostic.menuVisible = 'OBSERVED';
      return findRenameMenuItem();
    }, 2000);
  }
  if (!renameItem) throw renameUiError('DOT_RENAME_ACTION_NOT_FOUND', 'NOT_APPLIED', diagnostic);
  diagnostic.renameAction = 'FOUND';
  if (dotKeyFromLocation() !== key) {
    diagnostic.identity = 'MISMATCH';
    throw renameUiError('DOT_RENAME_TARGET_STALE', 'NOT_APPLIED', diagnostic);
  }
  activateRenameUiElement(renameItem);
  const input = await waitForRenameUi(() => findRenameEditor(anchor), 5000);
  if (!input) {
    diagnostic.editor = 'NOT_FOUND';
    throw renameUiError('DOT_RENAME_INPUT_NOT_FOUND', 'NOT_APPLIED', diagnostic);
  }
  diagnostic.editor = 'FOUND';
  return { input, scope: input.closest?.('[role="dialog"]') || input.closest?.('form') || null,
    diagnostic };
}

async function renameDotUi(message) {
  const key = String(message.dotKey || '').trim();
  const operationId = String(message.operationId || '').trim();
  const title = normalizedUiText(message.title);
  if (!key || dotKeyFromLocation() !== key) throw renameUiError('DOT_RENAME_TARGET_STALE');
  if (!operationId || !title || title.length > 100) throw renameUiError('DOT_RENAME_INPUT_INVALID');
  const { input, scope } = await openDotRenameEditor(key);
  setRenameEditorValue(input, title);
  if (dotKeyFromLocation() !== key) throw renameUiError('DOT_RENAME_TARGET_STALE');
  await renameSleep(80);
  let effectStarted = false;
  try {
    effectStarted = true;
    await submitRenameEditor(input, scope);
    const accepted = await waitForRenameUi(() =>
      (!document.contains(input) || !isVisible(input)) && currentDotTitleMatches(key, title), 8000
    );
    if (!accepted) throw renameUiError('DOT_RENAME_UI_NOT_VERIFIED', 'UNKNOWN');
    if (dotKeyFromLocation() !== key) throw renameUiError('DOT_RENAME_TARGET_STALE_AFTER_SAVE', 'UNKNOWN');
    return { ok: true, effectState: 'APPLIED', operationId, savedTitle: title };
  } catch (error) {
    if (error?.effectState) throw error;
    throw renameUiError(error?.message || error, effectStarted ? 'UNKNOWN' : 'NOT_APPLIED');
  }
}
