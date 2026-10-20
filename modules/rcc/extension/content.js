const RCC_BUILD_VERSION = '2026-10-20-rcc-core-shadow-v1';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));


function editorCandidates() {


  return [


    '#prompt-textarea',


    'div[contenteditable="true"][role="textbox"]',


    'div[contenteditable="true"][data-virtualkeyboard="true"]',


    'textarea[name="prompt-textarea"]'


  ];


}


function getEditor() {


  for (const selector of editorCandidates()) {


    const node = document.querySelector(selector);


    if (node) return node;


  }


  return null;


}


function conversationObserveRoot() {

  const main = document.querySelector('main') || document.querySelector('[role="main"]');

  if (main) return main;

  const turn = document.querySelector('[data-turn-key], [data-content-search-turn-key], [data-testid^="conversation-turn-"], [data-message-author-role="assistant"], [data-message-author-role="user"]');

  return turn?.closest?.('main') || turn?.parentElement || null;

}


function canonicalMessageUnit(node, role) {
  if (!(node instanceof Element)) return null;
  if (node.matches(`[data-message-author-role="${role}"]`)) {
    const semanticUnits = Array.from(node.querySelectorAll(
      `[data-content-search-unit-key$=":${role}"],[data-chatgpt-search-unit-key$=":${role}"]`
    ));
    if (semanticUnits.length === 1) return semanticUnits[0];
    return node;
  }
  const unit = node.matches('[data-content-search-unit-key]') ? node : node.closest('[data-content-search-unit-key]');
  if (unit) return unit;
  if (role === 'assistant') return node.closest('[data-chatgpt-search-unit-key]') || node;
  return node.closest('[data-user-message-bubble="true"]') || node;
}


function messageUnitRole(node) {
  if (!(node instanceof Element)) return '';
  const unit = node.matches('[data-content-search-unit-key],[data-chatgpt-search-unit-key]')
    ? node
    : node.closest('[data-content-search-unit-key],[data-chatgpt-search-unit-key]');
  return RelayCore.messageRoleFromEvidence({
    legacyRole: node.getAttribute('data-message-author-role') || node.closest('[data-message-author-role]')?.getAttribute('data-message-author-role') || '',
    unitKey: unit?.getAttribute('data-content-search-unit-key') || unit?.getAttribute('data-chatgpt-search-unit-key') || '',
    markdownStyle: node.getAttribute('data-markdown-text-style') || node.querySelector?.('[data-markdown-text-style]')?.getAttribute('data-markdown-text-style') || '',
    userBubble: node.matches('[data-user-message-bubble="true"]') || !!node.querySelector?.('[data-user-message-bubble="true"]')
  });
}


function getMessageUnits(role, root = document) {
  const selectors = role === 'assistant'
    ? ['[data-message-author-role="assistant"]', '[data-content-search-unit-key$=":assistant"]', '[data-chatgpt-search-unit-key$=":assistant"]', '[data-markdown-text-style="assistant-message"]']
    : ['[data-message-author-role="user"]', '[data-content-search-unit-key$=":user"]', '[data-user-message-bubble="true"]'];
  const seen = new Set();
  const units = [];
  for (const selector of selectors) {
    for (const node of root.querySelectorAll(selector)) {
      const unit = canonicalMessageUnit(node, role);
      if (!unit || seen.has(unit) || messageUnitRole(unit) !== role) continue;
      seen.add(unit);
      units.push(unit);
    }
  }
  return units;
}


function getConversationTurns() {
  const seen = new Set();
  const turns = [];
  for (const node of document.querySelectorAll('[data-turn-key], [data-content-search-turn-key], [data-testid^="conversation-turn-"]')) {
    const keyedDescendants = Array.from(node.querySelectorAll?.('[data-turn-key]') || []);
    const turn = node.matches('[data-turn-key]')
      ? node
      : node.closest('[data-turn-key]')
        || (keyedDescendants.length === 1 ? keyedDescendants[0] : node);
    if (seen.has(turn)) continue;
    seen.add(turn);
    turns.push(turn);
  }
  return turns;
}


function turnIdentity(turn) {
  if (!(turn instanceof Element)) return '';
  return turn.getAttribute('data-turn-key')
    || turn.getAttribute('data-content-search-turn-key')
    || turn.getAttribute('data-testid')
    || '';
}


function messageUnitText(node, role) {
  if (!(node instanceof Element)) return '';
  const content = role === 'assistant'
    ? node.querySelector('[data-markdown-text-style="assistant-message"], [data-message-author-role="assistant"] .markdown, .markdown') || node
    : node.querySelector('[data-user-message-bubble="true"], [data-message-author-role="user"]') || node;
  if (role === 'user') {
    // Long prompts are collapsed with an in-bubble "Show more" button.  That
    // UI chrome is not part of the submitted prompt identity.
    const clone = content.cloneNode(true);
    clone.querySelectorAll('button,[role="button"],[contenteditable="true"]').forEach((item) => item.remove());
    // Collapsed-message decoration is a sibling of the full text container,
    // not user text. Preserve literal ellipses and all unknown DOM shapes.
    clone.querySelectorAll('[data-search-result-target] + span[aria-hidden="true"]').forEach((item) => {
      if (item.textContent === '…') item.remove();
    });
    return RelayCore.normalizeMessageText(clone.textContent || '');
  }
  return RelayCore.normalizeMessageText(content.innerText || content.textContent || '');
}


function getAssistantNodes() {


  return getMessageUnits('assistant');


}


function lastAssistantNode() {


  const nodes = getAssistantNodes();


  return nodes.length ? nodes[nodes.length - 1] : null;


}


function hasCompletionAction() {


  const node = lastAssistantNode();


  if (!node) return false;


  const selectors = [


    'button[data-testid="copy-turn-action-button"]',


    'button[data-testid*="copy"]',


    'button[aria-label="Copy"]',


    'button[aria-label="\uBCF5\uC0AC"]',


    'button[aria-label="\uBCF5\uC0AC\uD558\uAE30"]'


  ];


  const scope = node.closest('[data-turn-key], [data-content-search-turn-key], [data-testid^="conversation-turn-"]') || node.parentElement || node;


  return selectors.some((selector) => {


    const button = scope.querySelector(selector);


    return !!button;


  });


}


function lastAssistantText() {


  const nodes = getAssistantNodes();


  if (!nodes.length) return '';


  const node = nodes[nodes.length - 1];


  return messageUnitText(node, 'assistant');


}


function messageIdentityEvidence(unit) {
  if (!(unit instanceof Element)) return { messageId: '', conflict: false };
  const ids = [];
  const selectionId = unit.getAttribute('data-chatgpt-selection-message-id')
    || unit.querySelector('[data-chatgpt-selection-message-id]')?.getAttribute('data-chatgpt-selection-message-id');
  const dilId = unit.getAttribute('data-dil-message-id')
    || unit.querySelector('[data-dil-message-id]')?.getAttribute('data-dil-message-id');
  const searchIds = String(unit.getAttribute('data-chatgpt-search-message-ids') || '').split(/\s+/).filter(Boolean);
  if (selectionId) ids.push(selectionId);
  if (dilId) ids.push(dilId);
  ids.push(...searchIds);
  const unique = Array.from(new Set(ids));
  return { messageId: unique[0] || '', conflict: unique.length > 1 };
}


function assistantCandidatesForTurn(turn) {
  const units = getMessageUnits('assistant', turn).filter((unit) => isVisible(unit));
  const leafUnits = units.filter((unit) =>
    !units.some((other) => other !== unit && unit.contains(other))
  );
  const finalUnits = leafUnits.length ? [leafUnits[leafUnits.length - 1]] : [];
  return finalUnits.map((unit) => {
    const identity = messageIdentityEvidence(unit);
    const unitKey = unit.getAttribute('data-content-search-unit-key') || unit.getAttribute('data-chatgpt-search-unit-key') || '';
    const markdownStyle = unit.getAttribute('data-markdown-text-style')
      || unit.querySelector('[data-markdown-text-style]')?.getAttribute('data-markdown-text-style')
      || '';
    const semanticAncestor = unit.closest(
      '[data-message-author-role="assistant"],[data-content-search-unit-key$=":assistant"],[data-chatgpt-search-unit-key$=":assistant"],[data-markdown-text-style="assistant-message"]'
    );
    const legacyRole = unit.getAttribute('data-message-author-role')
      || unit.querySelector('[data-message-author-role]')?.getAttribute('data-message-author-role')
      || semanticAncestor?.getAttribute('data-message-author-role')
      || '';
    const ancestorUnitKey = semanticAncestor?.getAttribute('data-content-search-unit-key')
      || semanticAncestor?.getAttribute('data-chatgpt-search-unit-key')
      || '';
    const ancestorMarkdownStyle = semanticAncestor?.getAttribute('data-markdown-text-style') || '';
    const roleEvidenceCount = Number(legacyRole === 'assistant')
      + Number(/(?:^|:)assistant$/i.test(unitKey) || /(?:^|:)assistant$/i.test(ancestorUnitKey))
      + Number(markdownStyle === 'assistant-message' || ancestorMarkdownStyle === 'assistant-message');
    return {
      messageId: identity.messageId,
      messageIdConflict: identity.conflict,
      text: messageUnitText(unit, 'assistant'),
      roleEvidenceCount
    };
  });
}


function turnUserText(turn) {
  const users = getMessageUnits('user', turn);
  if (users.length !== 1) return '';
  return messageUnitText(users[0], 'user');
}


function turnCompletionState(turn) {
  return String(turn?.getAttribute?.('data-talvt-turn-state')
    || turn?.querySelector?.('[data-talvt-turn-state]')?.getAttribute('data-talvt-turn-state')
    || '').trim().toLowerCase();
}


function turnHasStopAction(turn) {
  return !!turn?.querySelector?.('button[data-testid="stop-button"],button[aria-label="Stop streaming"],button[aria-label="Stop"],button[aria-label="\uC911\uC9C0"],button[aria-label*="\uC751\uB2F5 \uC911\uC9C0"]');
}


function turnGenerationInterrupted(turn) {
  const state = turnCompletionState(turn);
  if (/^(interrupted|cancelled|canceled|error|failed)$/.test(state)) return true;
  const buttons = Array.from(turn?.querySelectorAll?.('button') || []);
  return buttons.some((button) => /continue generating|continue response|\uACC4\uC18D \uC0DD\uC131|\uC751\uB2F5 \uACC4\uC18D/i.test([
    button.getAttribute('aria-label'), button.getAttribute('title'), button.textContent
  ].filter(Boolean).join(' ')));
}

function turnIsGenerating(turn) {
  if (!turn) return false;
  if (turnHasStopAction(turn)) return true;
  const state = turnCompletionState(turn);
  if (/^(streaming|generating|in_progress|in-progress|running)$/.test(state)) return true;
  return !!turn.querySelector?.('.result-streaming, [data-message-status="streaming"]');
}


function submittedPromptMatchesTurn(record, turn) {
  const rendered = turnUserText(turn);
  const submitted = RelayCore.normalizeMessageText(record?.submittedText || '');
  if (!rendered || !submitted) return false;
  if (rendered === submitted) return true;
  const inlineCodeRendered = RelayCore.normalizeMessageText(
    submitted.replace(/`([^`\r\n]+)`/g, '$1')
  );
  return rendered === inlineCodeRendered;
}


function resolveRoutedTurn(record) {
  const submittedText = RelayCore.normalizeMessageText(record.submittedText || '');
  if (!submittedText) return { ok: false, terminal: true, reason: 'ROUTE_PROMPT_IDENTITY_MISSING' };
  const currentKey = currentConversationKey();
  const turns = getConversationTurns();
  const before = new Set(Array.isArray(record.beforeTurnKeys) ? record.beforeTurnKeys : []);
  const matches = turns.filter((turn) => !before.has(turnIdentity(turn)) && submittedPromptMatchesTurn(record, turn));
  if (!record?.conversationKey || currentKey !== record.conversationKey) {
    // A first message starts on the blank route and ChatGPT may replace the
    // provisional document/route while the exact submitted turn is rendering.
    // Rebind only a genuinely blank bootstrap with one exact new user turn.
    if (record?.bootstrapCreatedTab !== true || !currentKey || before.size !== 0 || matches.length !== 1) {
      return { ok: false, terminal: true, reason: 'CONVERSATION_IDENTITY_CHANGED' };
    }
    record.conversationKey = currentKey;
    record.routeTurnKey = '';
  }
  if (record.routeTurnKey) {
    const exact = turns.filter((turn) => turnIdentity(turn) === record.routeTurnKey);
    if (exact.length !== 1) return { ok: false, terminal: false, reason: 'ROUTE_TURN_NOT_FOUND' };
    if (!submittedPromptMatchesTurn(record, exact[0])) return { ok: false, terminal: true, reason: 'ROUTE_TURN_USER_MISMATCH' };
    return { ok: true, turn: exact[0], turnKey: record.routeTurnKey };
  }
  if (matches.length > 1) return { ok: false, terminal: true, reason: 'ROUTE_TURN_AMBIGUOUS' };
  if (matches.length !== 1) return { ok: false, terminal: false, reason: 'ROUTE_TURN_NOT_RESOLVED' };
  return { ok: true, turn: matches[0], turnKey: turnIdentity(matches[0]) };
}


function isVisible(node) {


  return !!(node && node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden');


}


function connectionProblem() {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    return { disconnected: true, reason: 'browser-offline', message: 'navigator.onLine=false' };
  }
  const selectors = [
    '[role="alert"]',
    '[aria-live="assertive"]',
    '[aria-live="polite"]',
    '[data-sonner-toast]',
    '[data-testid*="toast"]'
  ];
  const patterns = [
    /연결이\s*(?:끊어졌|끊겼|종료되었)/i,
    /네트워크\s*오류/i,
    /재연결\s*중/i,
    /connection\s+lost/i,
    /disconnected/i,
    /network\s+error/i,
    /reconnecting/i,
    /you(?:'|’)re\s+offline|you\s+are\s+offline/i
  ];
  for (const selector of selectors) {
    for (const node of document.querySelectorAll(selector)) {
      if (node.closest?.('[data-message-author-role],[data-content-search-unit-key]')
        || node.querySelector?.('[data-message-author-role],[data-content-search-unit-key]')) continue;
      const text = String(node.textContent || node.innerText || '').trim();
      if (!text || text.length > 500 || !patterns.some((pattern) => pattern.test(text))) continue;
      return { disconnected: true, reason: 'chatgpt-connection-banner', message: text.slice(0, 240) };
    }
  }
  return { disconnected: false, reason: '', message: '' };
}

function isConnectionHealthy() {
  return connectionProblem().disconnected !== true;
}

async function waitForConnectionRecovery(timeoutMs = 120000) {
  if (isConnectionHealthy()) return { recovered: true, waitedMs: 0 };
  const started = Date.now();
  return new Promise((resolve, reject) => {
    let observer = null;
    let timer = null;
    let settled = false;
    const cleanup = () => {
      try { observer?.disconnect(); } catch (_) {}
      if (timer) clearTimeout(timer);
      try { window.removeEventListener('online', check); } catch (_) {}
    };
    const finish = (error = null) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (error) reject(error);
      else resolve({ recovered: true, waitedMs: Date.now() - started });
    };
    const check = () => {
      if (isConnectionHealthy()) finish();
    };
    observer = new MutationObserver(check);
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ['role','aria-live','data-testid','class']
    });
    window.addEventListener('online', check);
    timer = setTimeout(() => {
      const problem = connectionProblem();
      finish(new Error(`RELAY_CONNECTION_LOST_UNRECOVERED:${problem.reason || 'unknown'}`));
    }, timeoutMs);
    check();
  });
}

function isGenerating() {


  const stopSelectors = [


    'button[data-testid="stop-button"]',


    'button[aria-label="Stop streaming"]',


    'button[aria-label="Stop"]',


    'button[aria-label="\uC911\uC9C0"]',


    'button[aria-label*="\uC751\uB2F5 \uC911\uC9C0"]'


  ];


  // Background tabs can report zero client rects. Generation identity must not


  // depend on visibility; use DOM presence/status instead.


  if (stopSelectors.some((selector) => !!document.querySelector(selector))) return true;


  const node = lastAssistantNode();


  if (!node) return false;


  return node.matches('.result-streaming, [data-message-status="streaming"]') ||


    !!node.querySelector('.result-streaming, [data-message-status="streaming"]');


}


function isSendReady() {


  const selectors = [


    'button[data-testid="send-button"]',


    'button[aria-label="Send"]',


    'button[aria-label="\uBCF4\uB0B4\uAE30"]'


  ];


  return selectors.some((selector) => {


    const button = document.querySelector(selector);


    return button && !button.disabled && button.getClientRects().length > 0;


  });


}


function setEditorText(editor, text) {


  editor.focus();


  if (editor.tagName === 'TEXTAREA') {


    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;


    if (setter) setter.call(editor, text);


    else editor.value = text;


    editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));


    return;


  }


  const selection = window.getSelection();


  const range = document.createRange();


  range.selectNodeContents(editor);


  selection.removeAllRanges();


  selection.addRange(range);


  document.execCommand('delete', false);


  document.execCommand('insertText', false, text);


  editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));


}


function findReadySendButton(editor = null, options = {}) {
  // Only accept controls that explicitly identify themselves as ChatGPT send
  // controls. A page-wide form[type=submit] fallback can hit the new-chat
  // navigation form and turn "기깃" into ?prompt-textarea=기깃 without sending.
  const selectors = [
    'button[data-testid="send-button"]',
    'button[data-testid*="send-button"]',
    'button[aria-label="Send prompt"]',
    'button[aria-label="Send message"]',
    'button[aria-label="Send"]',
    'button[aria-label="메시지 보내기"]',
    'button[aria-label="프롬프트 보내기"]',
    'button[aria-label="보내기"]'
  ];

  const scopes = [];
  const form = editor?.closest?.('form');
  if (form) scopes.push(form);
  const composer = editor?.closest?.('[data-testid*="composer"], [data-testid="composer"]');
  if (composer && !scopes.includes(composer)) scopes.push(composer);
  if (options?.allowDocumentFallback !== false) scopes.push(document);

  for (const scope of scopes) {
    for (const selector of selectors) {
      const button = scope.querySelector(selector);
      if (button && button.isConnected !== false && !button.disabled &&
          button.getAttribute?.('aria-disabled') !== 'true' && button.getClientRects().length > 0) return button;
    }
  }
  return null;
}

function waitForReadySendButton(editor = null, timeoutMs = 8000, options = {}) {
  const findVerified = () => {
    if (typeof options?.expectedText === 'string') {
      if (getEditor() !== editor ||
          editorDraftText(editor) !== RelayCore.normalizeMessageText(options.expectedText)) return null;
    }
    return findReadySendButton(editor, options);
  };
  const existing = findVerified();
  if (existing) return Promise.resolve(existing);

  return new Promise((resolve) => {
    let observer = null;
    let timer = null;
    let settled = false;

    const finish = (button = null) => {
      if (settled) return;
      settled = true;
      try { observer?.disconnect(); } catch (_) {}
      if (timer) clearTimeout(timer);
      resolve(button);
    };

    const check = () => {
      const button = findVerified();
      if (button) finish(button);
    };

    observer = new MutationObserver(check);
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['disabled','class','aria-disabled','data-testid','aria-label']
    });
    timer = setTimeout(() => finish(null), timeoutMs);
    check();
  });
}

async function submitEditor(editor, options = {}) {
  const allowKeyboardFallback = options?.allowKeyboardFallback !== false;
  const waitMs = Number(options?.waitMs || 8000);
  const expected = typeof options?.expectedText === 'string'
    ? RelayCore.normalizeMessageText(options.expectedText) : null;
  const matchesDraft = () => expected === null ||
    (getEditor() === editor && editorDraftText(editor) === expected);
  if (!matchesDraft()) throw new Error('RELAY_EDITOR_TEXT_MISMATCH');
  // Wait for ChatGPT to swap its empty-composer voice control for the enabled send arrow.
  const button = await waitForReadySendButton(editor, waitMs, options);
  if (button) {
    if (!matchesDraft()) throw new Error('RELAY_EDITOR_TEXT_MISMATCH');
    // A React render may replace or disable the button after the observer resolved.
    if (findReadySendButton(editor, options) !== button) throw new Error('RELAY_SEND_BUTTON_CHANGED');
    const bindingAttestation = typeof options?.beforeSubmit === 'function'
      ? await options.beforeSubmit() : null;
    if (!matchesDraft()) throw new Error('RELAY_EDITOR_TEXT_MISMATCH');
    if (findReadySendButton(editor, options) !== button) throw new Error('RELAY_SEND_BUTTON_CHANGED');
    const activationAttestation = typeof options?.beforeActivation === 'function'
      ? (await options.beforeActivation(bindingAttestation)) || bindingAttestation
      : bindingAttestation;
    const readyAt = Date.now();
    button.click();
    return { ok: true, method: 'send-button', readyAt, clickedAt: Date.now(),
      bindingAttestation: activationAttestation };
  }
  if (!matchesDraft()) throw new Error('RELAY_EDITOR_TEXT_MISMATCH');

  if (!allowKeyboardFallback) {
    throw new Error('RELAY_SEND_BUTTON_NOT_READY');
  }

  // Existing-conversation relay keeps a bounded keyboard fallback. Provider
  // bootstrap must disable it because synthetic Enter on ChatGPT's new-chat
  // route can become ?prompt-textarea=... instead of sending a user turn.
  const bindingAttestation = typeof options?.beforeSubmit === 'function'
    ? await options.beforeSubmit() : null;
  if (!matchesDraft()) throw new Error('RELAY_EDITOR_TEXT_MISMATCH');
  const activationAttestation = typeof options?.beforeActivation === 'function'
    ? (await options.beforeActivation(bindingAttestation)) || bindingAttestation
    : bindingAttestation;
  editor.focus();
  for (const type of ['keydown', 'keypress', 'keyup']) {
    editor.dispatchEvent(new KeyboardEvent(type, {
      key: 'Enter', code: 'Enter', keyCode: 13, which: 13,
      bubbles: true, cancelable: true
    }));
  }
  return { ok: true, method: 'enter-fallback',
    bindingAttestation: activationAttestation };
}


async function waitForReply(beforeCount, beforeText, inactivityTimeoutMs = 360000, submittedAt = Date.now()) {

  return new Promise((resolve, reject) => {

    let sawNewAssistant = false;

    let sawGeneration = false;

    let lastText = beforeText || '';

    let stableSince = Date.now();

    let observer = null;

    let inactivityTimer = null;

    let stableTimer = null;

    let settled = false;

    let activityDeadline = Date.now() + inactivityTimeoutMs;

    let connectionRecoveryPromise = null;

    const requiredStableMs = 15000;


    const finish = (error, value) => {

      if (settled) return;

      settled = true;

      try { observer?.disconnect(); } catch (_) {}

      if (inactivityTimer) clearTimeout(inactivityTimer);

      if (stableTimer) clearTimeout(stableTimer);

      error ? reject(error) : resolve(value);

    };


    const armInactivity = (delayMs = inactivityTimeoutMs, resetDeadline = true) => {

      if (inactivityTimer) clearTimeout(inactivityTimer);
      if (resetDeadline) activityDeadline = Date.now() + inactivityTimeoutMs;

      inactivityTimer = setTimeout(() => {

        const phase = sawNewAssistant ? (sawGeneration ? 'generation observed' : 'new assistant turn observed') : 'no new assistant turn';

        finish(new Error('Timed out waiting for markerless ChatGPT completion (' + phase + '); delivery ambiguous'));

      }, Math.max(1, delayMs));

    };


    const evaluate = () => {

      if (settled) return;

      const problem = connectionProblem();
      if (problem.disconnected) {
        if (!connectionRecoveryPromise) {
          const outageStarted = Date.now();
          const remainingMs = Math.max(1, activityDeadline - outageStarted);
          if (inactivityTimer) { clearTimeout(inactivityTimer); inactivityTimer = null; }
          connectionRecoveryPromise = waitForConnectionRecovery().then(() => {
            const outageMs = Date.now() - outageStarted;
            activityDeadline += outageMs;
            stableSince = Date.now();
            connectionRecoveryPromise = null;
            armInactivity(remainingMs, false);
            evaluate();
          }).catch((error) => finish(error));
        }
        return;
      }

      const nodes = getAssistantNodes();

      const text = lastAssistantText();

      const generating = isGenerating();


      if (nodes.length > beforeCount) sawNewAssistant = true;

      if (generating) sawGeneration = true;


      if (text !== lastText) {

        lastText = text;

        stableSince = Date.now();

        armInactivity();

        if (stableTimer) { clearTimeout(stableTimer); stableTimer = null; }

      } else if (generating) {

        armInactivity();

      }


      if (generating) {

        if (stableTimer) { clearTimeout(stableTimer); stableTimer = null; }

        return;

      }

      if (!sawNewAssistant || !text || text === beforeText) return;


      const stableForMs = Date.now() - stableSince;

      if (stableForMs < requiredStableMs) {

        if (stableTimer) clearTimeout(stableTimer);

        stableTimer = setTimeout(() => { stableTimer = null; evaluate(); }, requiredStableMs - stableForMs);

        return;

      }


      const completionUiReady = hasCompletionAction();

      const generationStartedAt = Number(telemetry?.generationStartedAt || 0);

      const generationFinishedAt = Number(telemetry?.generationFinishedAt || 0);

      const generationLifecycleComplete = !!(!generating && typeof telemetry === 'object' &&

        telemetry?.generationState === 'IDLE' && telemetry?.readiness === 'READY' &&

        generationStartedAt >= (Number(submittedAt) - 1000) && generationFinishedAt >= generationStartedAt);


      if (RelayCore.shouldPromoteReply({

        sawNewAssistant,

        sawGeneration,

        generating,

        completionUiReady,

        generationLifecycleComplete,

        textChanged: text !== beforeText,

        stableForMs

      })) finish(null, text.trim());

    };


    const root = conversationObserveRoot();

    if (!root) {

      finish(new Error('ChatGPT conversation root not found'));

      return;

    }

    observer = new MutationObserver(evaluate);

    observer.observe(root, {

      childList: true,

      subtree: true,

      characterData: true,

      attributes: true,

      attributeFilter: ['class','data-message-status','data-testid','aria-label','data-talvt-turn-state','data-content-search-unit-key']

    });

    armInactivity();

    evaluate();

  });

}


async function waitForEditor(timeoutMs = 15000) {
  const existing = getEditor();
  if (existing) return existing;

  return new Promise((resolve, reject) => {
    let observer = null;
    let timer = null;
    let settled = false;

    const finish = (error, editor = null) => {
      if (settled) return;
      settled = true;
      try { observer?.disconnect(); } catch (_) {}
      if (timer) clearTimeout(timer);
      error ? reject(error) : resolve(editor);
    };

    const check = () => {
      const editor = getEditor();
      if (editor) finish(null, editor);
    };

    observer = new MutationObserver(check);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    timer = setTimeout(() => finish(new Error('ChatGPT input box not found after 15s')), timeoutMs);
    check();
  });
}


// The actual user turn and the operation-fenced network-start signal are two
// independent affirmative proofs. Neither needs to wait for the other's timeout.
function editorDraftText(editor) {
  if (!editor) return '';
  let raw = '';
  if (editor.tagName === 'TEXTAREA') raw = editor.value;
  else {
    // ProseMirror renders one inserted newline as adjacent paragraphs, while
    // innerText exposes a blank line between those blocks. Reconstruct the
    // draft from its direct paragraph blocks so the exact pre-submit fence
    // compares the text that was inserted rather than browser layout spacing.
    const children = Array.from(editor.children || []);
    const paragraphDraft = children.length > 0
      && children.every((node) => ['P', 'DIV'].includes(String(node.tagName || '').toUpperCase()));
    raw = paragraphDraft
      ? children.map((node) => node.innerText || node.textContent || '').join('\n')
      : (editor.innerText || editor.textContent || '');
  }
  return RelayCore.normalizeMessageText(raw);
}

function waitForExactUserSubmission(expectedText, beforeUserCount, timeoutMs = 8000) {
  const expected = RelayCore.normalizeMessageText(expectedText || '');
  return new Promise((resolve, reject) => {
    let settled = false;
    let observer = null;
    let timer = null;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      try { observer?.disconnect(); } catch (_) {}
      if (timer) clearTimeout(timer);
      error ? reject(error) : resolve(true);
    };
    const check = () => {
      const users = getMessageUnits('user');
      if (users.length <= beforeUserCount) return;
      const added = users.slice(beforeUserCount);
      if (added.some((node) => messageUnitText(node, 'user') === expected)) finish();
    };
    observer = new MutationObserver(check);
    observer.observe(conversationObserveRoot() || document.body, { childList: true, subtree: true, characterData: true });
    timer = setTimeout(() => finish(new Error('RELAY_EXACT_USER_TURN_NOT_CONFIRMED')), timeoutMs);
    check();
  });
}


async function sendPrompt(text, tracking = null, awaitReply = true) {


  if (isGenerating()) throw new Error('Target ChatGPT tab is already generating');


  const editor = await waitForEditor();

  if (editorDraftText(editor)) throw new Error('RELAY_COMPOSER_NOT_EMPTY');


  const beforeCount = getAssistantNodes().length;


  const beforeText = lastAssistantText();

  const beforeUserCount = getMessageUnits('user').length;


  setEditorText(editor, text);


  await submitEditor(editor);

  await waitForExactUserSubmission(text, beforeUserCount);


  if (tracking?.relayId) saveRelayExecution({
    ...tracking,
    relayId: tracking.relayId,
    conversationKey: currentConversationKey(),
    beforeCount,
    beforeText,
    phase: 'submitted',
    submittedAt: Date.now(),
  });

  if (!awaitReply) return { submitted: true, beforeCount, beforeText };

  return waitForReply(beforeCount, beforeText);


}

// V0 is a one-way, verbatim hand-off between two explicitly bound
// conversations. It does not create a legacy relay record, queue a prompt,
// wait for an assistant response, or interpret that response.
async function executeSimpleRelayV0(message) {
  const expectedConversationKey = String(message?.conversationKey || '').trim().toLowerCase();
  const relayId = String(message?.relayId || '').trim();
  const text = String(message?.text || '');
  if (!relayId || !expectedConversationKey || !text || text.length > 12000) {
    return { ok: false, submitted: false, effectState: 'NOT_APPLIED', error: 'SIMPLE_RELAY_ARGUMENT_INVALID' };
  }
  if (currentConversationKey() !== expectedConversationKey) {
    return { ok: false, submitted: false, effectState: 'NOT_APPLIED', error: 'SIMPLE_RELAY_CONVERSATION_MISMATCH' };
  }
  try {
    const record = {
      relayId,
      conversationKey: expectedConversationKey,
      submittedText: RelayCore.normalizeMessageText(text),
      beforeTurnKeys: getConversationTurns().map(turnIdentity).filter(Boolean),
      routeTurnKey: '',
    };
    const submission = await sendPrompt(text, record, false);
    if (currentConversationKey() !== expectedConversationKey) {
      return { ok: false, submitted: false, effectState: 'UNKNOWN', error: 'SIMPLE_RELAY_CONVERSATION_CHANGED_AFTER_SUBMIT' };
    }
    const persistedRecord = loadRelayExecution() || record;
    const routed = resolveRoutedTurn(persistedRecord);
    if (!routed.ok || !routed.turnKey) {
      clearRelayExecution(relayId);
      return { ok: false, submitted: false, effectState: 'UNKNOWN', error: 'SIMPLE_RELAY_ROUTE_TURN_UNVERIFIED' };
    }
    persistedRecord.routeTurnKey = routed.turnKey;
    saveRelayExecution(persistedRecord);
    return { ok: true, submitted: true, relayId, conversationKey: expectedConversationKey,
      beforeAssistantCount: Number(submission?.beforeCount || 0) };
  } catch (error) {
    return { ok: false, submitted: false, effectState: 'UNKNOWN',
      error: String(error?.message || error || 'SIMPLE_RELAY_SUBMIT_FAILED') };
  }
}

// This read is intentionally narrow: it returns only the response that appeared
// after the exact Simple Relay submission. It neither sends, queues, summarizes,
// nor marks the response as consumed.
async function readSimpleRelayV0Reply(message) {
  const expectedConversationKey = String(message?.conversationKey || '').trim().toLowerCase();
  const afterAssistantCount = Number(message?.afterAssistantCount);
  const relayId = String(message?.relayId || '').trim();
  if (!expectedConversationKey || !Number.isInteger(afterAssistantCount) || afterAssistantCount < 0) {
    return { ok: false, effectState: 'NOT_APPLIED', error: 'SIMPLE_RELAY_READ_ARGUMENT_INVALID' };
  }
  if (currentConversationKey() !== expectedConversationKey) {
    return { ok: false, effectState: 'NOT_APPLIED', error: 'SIMPLE_RELAY_READ_CONVERSATION_MISMATCH' };
  }
  if (isGenerating()) {
    return { ok: false, effectState: 'NOT_APPLIED', error: 'SIMPLE_RELAY_REPLY_STILL_GENERATING' };
  }
  const record = loadRelayExecution();
  if (!relayId || record?.relayId !== relayId || record?.conversationKey !== expectedConversationKey) {
    return { ok: false, effectState: 'NOT_APPLIED', error: 'SIMPLE_RELAY_ROUTE_RECORD_MISSING' };
  }
  try {
    const responseText = recoverCompletedReplyFromDom(record);
    if (responseText.length > 12000) {
      return { ok: false, effectState: 'NOT_APPLIED', error: 'SIMPLE_RELAY_REPLY_TOO_LARGE' };
    }
    return { ok: true, conversationKey: expectedConversationKey, responseText };
  } catch (error) {
    return { ok: false, effectState: 'NOT_APPLIED',
      error: String(error?.message || error || 'SIMPLE_RELAY_NEW_REPLY_NOT_READY').slice(0, 200) };
  }
}

function currentConversationKey() {


  return RelayCore.conversationKey(location.href);


}


const RELAY_EXECUTION_KEY = 'relayActiveExecutionV1';
// Only exact durable-receipt retirement adds an ID. Late collectors in this
// document must not resurrect it after a new relay has entered the composer.
const retiredRelayExecutions = new Set();


function loadRelayExecution() { try { return JSON.parse(sessionStorage.getItem(RELAY_EXECUTION_KEY) || 'null'); } catch (_) { return null; } }


function saveRelayExecution(value) { if (retiredRelayExecutions.has(value?.relayId)) return; try { sessionStorage.setItem(RELAY_EXECUTION_KEY, JSON.stringify(value)); } catch (_) {} }


function clearRelayExecution(relayId) { const current=loadRelayExecution(); if (!relayId || current?.relayId===relayId) try { sessionStorage.removeItem(RELAY_EXECUTION_KEY); } catch (_) {} }


const RELAY_DEFERRED_QUEUE_KEY = 'relayDeferredQueueV1';


function loadDeferredRelayQueue() { try { const q=JSON.parse(sessionStorage.getItem(RELAY_DEFERRED_QUEUE_KEY) || '[]'); return Array.isArray(q) ? q : []; } catch (_) { return []; } }


let deferredDrainTimer = null;


function recoverCompletedReplyFromDom(record) {
  const routed = resolveRoutedTurn(record);
  if (!routed.ok) throw new Error(`RELAY_RECOVERY_DOM_UNKNOWN:${routed.reason}`);
  if (!submittedPromptMatchesTurn(record, routed.turn)) throw new Error('RELAY_RECOVERY_PROMPT_IDENTITY_MISMATCH');
  if (turnGenerationInterrupted(routed.turn)) throw new Error('RELAY_RECOVERY_ASSISTANT_INTERRUPTED');

  const completeState = turnCompletionState(routed.turn) === 'complete';
  const completionUiReady = !!routed.turn.querySelector(
    'button[data-testid="copy-turn-action-button"],button[data-testid*="copy"],button[aria-label="Copy"],button[aria-label="복사"],button[aria-label="복사하기"]'
  );
  // ChatGPT can leave an inert stop control in the document after a completed
  // background turn.  Treat it as stale only when the exact routed turn has
  // both independent terminal signals.  Otherwise recovery remains fail-closed.
  const exactTurnTerminal = completeState && completionUiReady;
  if (!exactTurnTerminal && turnIsGenerating(routed.turn)) {
    throw new Error('RELAY_RECOVERY_ASSISTANT_STILL_STREAMING');
  }

  const candidates = assistantCandidatesForTurn(routed.turn);
  const selected = RelayCore.selectAssistantCandidate(candidates);
  if (!selected.ok) throw new Error(`RELAY_RECOVERY_DOM_UNKNOWN:${selected.reason}`);

  if (!completeState && !completionUiReady) throw new Error('RELAY_RECOVERY_FINAL_STATE_UNKNOWN');
  return selected.candidate.text;
}

function normalizedUiText(value) { return String(value || '').replace(/\s+/g, ' ').trim(); }


chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
if (message.type === 'relay:recoverExecution') {
    const storedRecord = loadRelayExecution();
    const suppliedRecord = message.recoveryRecord && typeof message.recoveryRecord === 'object'
      ? message.recoveryRecord : null;
    const record = storedRecord?.relayId ? storedRecord : suppliedRecord;
    const relayId = String(message.relayId || '');
    if (!record?.relayId || (relayId && record.relayId !== relayId)) {
      sendResponse({ ok: false, recovered: false, error: 'RELAY_RECOVERY_RECORD_NOT_FOUND' });
      return;
    }
    const conversationKey = String(record.conversationKey || currentConversationKey());
    if (!conversationKey || conversationKey !== currentConversationKey()) {
      sendResponse({ ok: false, recovered: false, error: 'RELAY_RECOVERY_IDENTITY_MISMATCH' });
      return;
    }
    Promise.resolve().then(() => recoverCompletedReplyFromDom({ ...record, conversationKey }))
      .then((recoveredReply) => sendResponse({ ok: true, recovered: true, relayId: record.relayId, recoveredReply }))
      .catch((error) => sendResponse({ ok: false, recovered: false, error: error.message }));
    return true;
  }

if (message.type === 'relay:activityProbe') {
    sampleJsHeapTelemetry();


    sendResponse({


      ok: true,


      generating: isGenerating(),

      connection: connectionProblem(),


      telemetry: typeof telemetry === 'object' ? {generationState:telemetry.generationState||'',readiness:telemetry.readiness||'IDLE',lastActivityAt:telemetry.lastActivityAt||null,lastCommandAt:telemetry.lastCommandAt||null,generationStartedAt:telemetry.generationStartedAt||null,generationFinishedAt:telemetry.generationFinishedAt||null,queueDelayMs:telemetry.queueDelayMs??null,generationTimeMs:telemetry.generationTimeMs??null,totalResponseTimeMs:telemetry.totalResponseTimeMs??null,rollingAvgResponseMs:telemetry.rollingAvgResponseMs??null,rollingP95ResponseMs:telemetry.rollingP95ResponseMs??null,performanceState:telemetry.performanceState||'NORMAL',user_count:telemetry.user_count??null,assistant_count:telemetry.assistant_count??null,turns:telemetry.turns??null,rendered_chars:telemetry.rendered_chars??null,js_heap_used_mb:telemetry.js_heap_used_mb??null,js_heap_limit_mb:telemetry.js_heap_limit_mb??null,usage_estimate_kind:telemetry.usage_estimate_kind||'incremental-message-chars-v1',buildVersion:RCC_BUILD_VERSION} : null


    });


    return;


  }

if (message.type === 'relay:probe') {
    sampleJsHeapTelemetry();


    const nodes = getAssistantNodes();


    const activeExecution = loadRelayExecution();


    const deferredQueue = loadDeferredRelayQueue();


    sendResponse({


      ok: true,


      contentVersion: 'markerless-v3-stable-final',

      buildVersion: RCC_BUILD_VERSION,


      generating: isGenerating(),

      connection: connectionProblem(),

      activeExecution: activeExecution?.relayId ? {

        relayId: String(activeExecution.relayId), phase: String(activeExecution.phase || ''),

        conversationKey: String(activeExecution.conversationKey || ''),

        submittedAt: Number(activeExecution.submittedAt || 0) || null

      } : null,

      deferredQueueDepth: deferredQueue.length,


      telemetry: typeof telemetry === 'object' ? {generationState:telemetry.generationState||'',readiness:telemetry.readiness||'IDLE',lastActivityAt:telemetry.lastActivityAt||null,lastCommandAt:telemetry.lastCommandAt||null,generationStartedAt:telemetry.generationStartedAt||null,generationFinishedAt:telemetry.generationFinishedAt||null,queueDelayMs:telemetry.queueDelayMs??null,generationTimeMs:telemetry.generationTimeMs??null,totalResponseTimeMs:telemetry.totalResponseTimeMs??null,rollingAvgResponseMs:telemetry.rollingAvgResponseMs??null,rollingP95ResponseMs:telemetry.rollingP95ResponseMs??null,performanceState:telemetry.performanceState||'NORMAL',user_count:telemetry.user_count??null,assistant_count:telemetry.assistant_count??null,turns:telemetry.turns??null,rendered_chars:telemetry.rendered_chars??null,js_heap_used_mb:telemetry.js_heap_used_mb??null,js_heap_limit_mb:telemetry.js_heap_limit_mb??null,usage_estimate_kind:telemetry.usage_estimate_kind||'incremental-message-chars-v1'} : null,


      assistantCount: nodes.length,


      completionUiReady: hasCompletionAction(),


      sendReady: isSendReady(),


      assistantStatus: lastAssistantNode()?.getAttribute('data-message-status') || '',


      assistantClass: String(lastAssistantNode()?.className || ''),


      assistantButtons: Array.from(lastAssistantNode()?.querySelectorAll('button') || []).slice(0, 20).map((b) => ({


        testid: b.getAttribute('data-testid') || '', aria: b.getAttribute('aria-label') || '', disabled: !!b.disabled


      })),


      composerButtons: Array.from(document.querySelectorAll('form button')).slice(-20).map((b) => ({


        testid: b.getAttribute('data-testid') || '', aria: b.getAttribute('aria-label') || '', disabled: !!b.disabled,


        type: b.getAttribute('type') || ''


      }))


    });


    return;


  }

if (message.type === 'relay:simpleExecute') {

    executeSimpleRelayV0(message).then(sendResponse).catch((error) => sendResponse({
      ok: false, submitted: false, effectState: 'UNKNOWN', error: error.message
    }));

    return true;


  }

if (message.type === 'relay:simpleReadReply') {

    readSimpleRelayV0Reply(message).then(sendResponse).catch((error) => sendResponse({
      ok: false, effectState: 'NOT_APPLIED', error: error.message
    }));

    return true;


  }
  sendResponse({ ok: false, error: `RCC_CONTENT_MESSAGE_DISABLED:${String(message?.type || '')}` });
  return false;
});


const telemetryKey = 'dwActTelemetryV1';


let telemetry = (() => { try { return JSON.parse(sessionStorage.getItem(telemetryKey) || '{}'); } catch (_) { return {}; } })();


telemetry.responseSamples = Array.isArray(telemetry.responseSamples) ? telemetry.responseSamples.slice(-20) : [];


function persistTelemetry() { try { sessionStorage.setItem(telemetryKey, JSON.stringify(telemetry)); } catch (_) {} }


function messageNodes(role) { return getMessageUnits(role); }

function sampleJsHeapTelemetry() {
  const memory = performance?.memory;
  if (!memory) return;
  const used = Number(memory.usedJSHeapSize);
  const limit = Number(memory.jsHeapSizeLimit);
  if (Number.isFinite(used) && used >= 0) telemetry.js_heap_used_mb = Math.round((used / 1048576) * 10) / 10;
  if (Number.isFinite(limit) && limit > 0) telemetry.js_heap_limit_mb = Math.round((limit / 1048576) * 10) / 10;
}


function seedConversationUsageOnce(force = false) {


  if (!force && Number.isFinite(Number(telemetry.rendered_chars)) && Number.isFinite(Number(telemetry.turns)) && Number(telemetry.rendered_chars) > 0) return;


  const users = Array.from(messageNodes('user')), assistants = Array.from(messageNodes('assistant'));


  const turnNodes = getConversationTurns();


  const fallbackTurns = turnNodes.length ? turnNodes : Array.from(document.querySelectorAll('main article')).filter((node) => String(node?.innerText || node?.textContent || '').trim());


  const roleNodes = users.length || assistants.length ? [...users, ...assistants] : [];


  const usageNodes = roleNodes.length ? roleNodes : fallbackTurns;


  let chars = 0;


  for (const node of usageNodes) chars += String((node?.querySelector?.('.markdown') || node)?.innerText || node?.textContent || '').length;


  telemetry.user_count = roleNodes.length ? users.length : null;


  telemetry.assistant_count = roleNodes.length ? assistants.length : null;


  telemetry.turns = roleNodes.length ? Math.max(users.length, assistants.length) : fallbackTurns.length;


  telemetry.rendered_chars = chars;


  telemetry.usage_estimate_kind = roleNodes.length ? 'message-role-chars-v2' : 'conversation-turn-chars-v2';


  persistTelemetry();


}


function appendNewMessageUsage(role) {


  const nodes = messageNodes(role);


  const key = role === 'user' ? 'user_count' : 'assistant_count';


  let previous = Number(telemetry[key]);


  if (!Number.isFinite(previous) || previous < 0) previous = 0;


  let chars = Number(telemetry.rendered_chars);


  if (!Number.isFinite(chars) || chars < 0) chars = 0;


  for (let i = previous; i < nodes.length; i += 1) chars += String(nodes[i]?.textContent || '').length;


  telemetry[key] = nodes.length;


  telemetry.turns = Math.min(Number(telemetry.user_count) || 0, Number(telemetry.assistant_count) || 0);


  telemetry.rendered_chars = chars;


  telemetry.usage_estimate_kind = 'incremental-message-chars-v1';


}


seedConversationUsageOnce();


const RELAY_USER_ATTENTION_RULES = [


  { kind:'NEW_CHAT_REQUIRED', label:'새 채팅 필요', re:/(maximum length for (?:this )?conversation|conversation is too long|reached the maximum length|start a new (?:chat|conversation|one)|대화.{0,20}(?:최대 길이|너무 깁니다|길이 제한)|새 (?:채팅|대화).{0,20}(?:시작|계속))/i },


  { kind:'RECOVERY_REQUIRED', label:'새로고침 / 복구 필요', re:/(problem preparing your chat|unable to load (?:the )?(?:chat|conversation)|failed to load (?:the )?(?:chat|conversation)|please (?:reload|refresh)|(?:reload|refresh) the page|대화.{0,30}(?:불러오|로드).{0,20}(?:실패|문제)|페이지.{0,20}(?:새로고침|다시 로드))/i },


  { kind:'RETRY_REQUIRED', label:'다시 시도 필요', re:/(there was an error generating a response|a network error occurred|something went wrong|message.{0,30}(?:timed out|took too long)|request timed out|websocket.{0,30}(?:error|failed)|응답.{0,30}(?:오류|실패|시간.*초과)|네트워크.{0,20}오류|메시지.{0,30}(?:시간.*초과|전송.*실패)|요청.{0,20}시간.*초과|문제가 발생)/i }


];


const RELAY_USER_ATTENTION_TEXT_RE = new RegExp(RELAY_USER_ATTENTION_RULES.map((rule) => rule.re.source).join('|'), 'i');


function relayUserAttentionText(node) {


  if (!node) return '';


  const aria = node.getAttribute?.('aria-label') || '';


  return normalizedUiText([aria, node.innerText, node.textContent].filter(Boolean).join(' ')).slice(0, 1600);


}


function relayUserAttentionUiNode(node) {


  return node instanceof Element && isVisible(node) && !node.closest('[data-message-author-role]');


}


function detectRelayUserAttention() {


  const selector = '[role="alert"],[role="dialog"],[role="status"],[data-testid*="error" i],[data-testid*="retry" i],[data-testid*="reload" i],[data-testid*="refresh" i],main [class*="error" i],main [class*="warning" i]';


  const nodes = [...document.querySelectorAll(selector)].filter(relayUserAttentionUiNode);


  for (const node of nodes) {


    const text = relayUserAttentionText(node);


    for (const rule of RELAY_USER_ATTENTION_RULES) if (rule.re.test(text)) return { kind:rule.kind, label:rule.label };


  }


  const buttons = [...document.querySelectorAll('button')].filter(relayUserAttentionUiNode);


  for (const button of buttons) {


    const text = relayUserAttentionText(button);


    if (/^(retry|try again|다시 시도|재시도|응답 재생성|regenerate(?: response)?)$/i.test(text)) return { kind:'RETRY_REQUIRED', label:'다시 시도 필요' };


    if (/^(reload|refresh|새로고침|페이지 새로고침)$/i.test(text)) return { kind:'RECOVERY_REQUIRED', label:'새로고침 / 복구 필요' };


  }


  return null;


}


let lastReportedGenerating = null;


let lastReportedReadiness = '';


let lastReportedUserAttentionSignature = '';

async function reportGenerationSignal(generating, source = 'dom', force = false) {


  const now = Date.now();


  generating = !!generating;


  if (force) seedConversationUsageOnce(true);


  const readiness = generating ? 'BUSY' : (source === 'network' ? 'READY' : (source === 'network-error' ? 'UNKNOWN' : 'IDLE'));


  const userAttention = detectRelayUserAttention();


  const userAttentionSignature = userAttention ? `${userAttention.kind}:${userAttention.label}` : '';


  if (!force && generating === lastReportedGenerating && readiness === lastReportedReadiness && userAttentionSignature === lastReportedUserAttentionSignature) return;


  const wasGenerating = lastReportedGenerating === true;


  lastReportedGenerating = generating;


  lastReportedReadiness = readiness;


  lastReportedUserAttentionSignature = userAttentionSignature;


  telemetry.userAttention = userAttention;


  telemetry.lastActivityAt = now;


  telemetry.generationState = generating ? 'GENERATING' : 'IDLE';


  telemetry.readiness = generating ? 'BUSY' : (source === 'network' ? 'READY' : (source === 'network-error' ? 'UNKNOWN' : 'IDLE'));


  if (generating) {


    appendNewMessageUsage('user');


    telemetry.generationStartedAt = now;


  }


  if (!generating && wasGenerating) {


    appendNewMessageUsage('assistant');


    telemetry.generationFinishedAt = now;


    if (telemetry.generationStartedAt) telemetry.generationTimeMs = Math.max(0, now - telemetry.generationStartedAt);


  }


  sampleJsHeapTelemetry();
  persistTelemetry();


  try {


    await chrome.runtime.sendMessage({


      type:'relay:activity', generating, url:location.href,

      connection: connectionProblem(),


      telemetry:{generationState:telemetry.generationState,readiness:telemetry.readiness||'IDLE',lastActivityAt:telemetry.lastActivityAt,generationStartedAt:telemetry.generationStartedAt||null,generationFinishedAt:telemetry.generationFinishedAt||null,generationTimeMs:telemetry.generationTimeMs??null,user_count:telemetry.user_count??null,assistant_count:telemetry.assistant_count??null,turns:telemetry.turns??null,rendered_chars:telemetry.rendered_chars??null,js_heap_used_mb:telemetry.js_heap_used_mb??null,js_heap_limit_mb:telemetry.js_heap_limit_mb??null,usage_estimate_kind:telemetry.usage_estimate_kind||'incremental-message-chars-v1',user_attention:telemetry.userAttention||null,signal_source:source}


    });


  } catch (_) {}

}


async function reportGenerationState() { return reportGenerationSignal(isGenerating(), 'dom'); }


let relayGenerationConversationKey = currentConversationKey();


let relayGenerationCheckScheduled = false;


function relayGenerationMutationRelevant(mutation) {
  const target = mutation.target instanceof Element ? mutation.target : mutation.target?.parentElement || null;

  if (mutation.type === 'attributes') {
    if (!['class','data-message-status','data-testid','aria-label','data-talvt-turn-state','data-content-search-unit-key'].includes(String(mutation.attributeName || ''))) return false;
    if (!target) return false;
    return target.matches(
      'button[data-testid="stop-button"],button[aria-label="Stop streaming"],button[aria-label="Stop"],button[aria-label="중지"],button[aria-label*="응답 중지"],[data-message-author-role="assistant"],[data-content-search-unit-key$=":assistant"],[data-talvt-turn-state],.result-streaming,[data-message-status]'
    ) || !!target.closest('[data-message-author-role="assistant"],[data-content-search-unit-key$=":assistant"],[data-turn-key]');
  }

  if (mutation.type !== 'childList') return false;
  const selector = 'button[data-testid="stop-button"],button[aria-label="Stop streaming"],button[aria-label="Stop"],button[aria-label="중지"],button[aria-label*="응답 중지"],[data-message-author-role="assistant"],[data-content-search-unit-key$=":assistant"],[data-talvt-turn-state],.result-streaming,[data-message-status]';
  return [...mutation.addedNodes, ...mutation.removedNodes].some((node) => {
    if (!(node instanceof Element)) return false;
    return node.matches(selector) || !!node.querySelector(selector);
  });
}

function relayUserAttentionMutationRelevant(mutation) {
  if (mutation.type !== 'childList') return false;
  const selector = '[role="alert"],[role="dialog"],[role="status"],[data-testid*="error" i],[data-testid*="retry" i],[data-testid*="reload" i],[data-testid*="refresh" i]';
  return [...mutation.addedNodes, ...mutation.removedNodes].some((node) => {
    if (node instanceof Text) {
      const parent = node.parentElement;
      if (!parent || parent.closest('[data-message-author-role],[data-content-search-unit-key]')) return false;
      return RELAY_USER_ATTENTION_TEXT_RE.test(normalizedUiText(node.textContent).slice(0, 1600));
    }
    if (!(node instanceof Element)) return false;
    if (node.matches(selector) || !!node.querySelector(selector)) return true;
    if (node.closest('[data-message-author-role],[data-content-search-unit-key]')) return false;
    return RELAY_USER_ATTENTION_TEXT_RE.test(normalizedUiText(node.textContent).slice(0, 1600));
  });
}


function scheduleRelayGenerationStateCheck(force = false) {


  if (relayGenerationCheckScheduled && !force) return;


  relayGenerationCheckScheduled = true;


  queueMicrotask(() => {


    relayGenerationCheckScheduled = false;


    const key = currentConversationKey();


    const routeChanged = key !== relayGenerationConversationKey;


    if (routeChanged) {


      relayGenerationConversationKey = key;


      lastReportedGenerating = null;


      lastReportedReadiness = '';


      lastReportedUserAttentionSignature = '';


    }


    reportGenerationSignal(isGenerating(), 'dom', force || routeChanged).catch(() => {});


  });


}


const relayGenerationObserver = new MutationObserver((mutations) => {
  if (mutations.some(relayGenerationMutationRelevant)) scheduleRelayGenerationStateCheck(false);
});

const relayGenerationRoot = conversationObserveRoot();
if (relayGenerationRoot) {
  relayGenerationObserver.observe(relayGenerationRoot, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class','data-message-status','data-testid','aria-label','data-talvt-turn-state','data-content-search-unit-key']
  });
}

const relayAttentionObserver = new MutationObserver((mutations) => {
  if (mutations.some(relayUserAttentionMutationRelevant)) scheduleRelayGenerationStateCheck(false);
});
relayAttentionObserver.observe(document.documentElement, { childList: true, subtree: true });


window.addEventListener('focus', () => scheduleRelayGenerationStateCheck(false));


document.addEventListener('visibilitychange', () => { if (!document.hidden) scheduleRelayGenerationStateCheck(false); });


window.addEventListener('pageshow', () => scheduleRelayGenerationStateCheck(false));


reportGenerationState().catch(() => {});

window.addEventListener('online', () => reportGenerationState().catch(() => {}));
window.addEventListener('offline', () => reportGenerationState().catch(() => {}));
