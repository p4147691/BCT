const RCC_BUILD_VERSION = '2026-10-24-rcc-reasoning-observation-v1';

function editorCandidates() {


  return [


    '#prompt-textarea',


    'div[contenteditable="true"][data-virtualkeyboard="true"]',


    'textarea[name="prompt-textarea"]',


    'form div[contenteditable="true"][role="textbox"]'


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
  // New ChatGPT DOM builds can expose a stable semantic user unit before
  // its enclosing turn wrapper. Admit only the role-keyed user unit not
  // already represented by a turn; exact-text/uniqueness gates still apply.
  const wrapperSelector =
    '[data-turn-key], [data-content-search-turn-key], [data-testid^="conversation-turn-"]';
  for (const unit of document.querySelectorAll(
    '[data-content-search-unit-key$=":user"], [data-chatgpt-search-unit-key$=":user"]'
  )) {
    if (!unit.matches('[data-content-search-unit-key$=":user"], [data-chatgpt-search-unit-key$=":user"]')
        || unit.closest(wrapperSelector) || messageUnitRole(unit) !== 'user'
        || !turnIdentity(unit) || seen.has(unit)) continue;
    seen.add(unit);
    turns.push(unit);
  }
  return turns;
}

function turnIdentity(turn) {
  if (!(turn instanceof Element)) return '';
  return turn.getAttribute('data-turn-key')
    || turn.getAttribute('data-content-search-turn-key')
    || turn.getAttribute('data-testid')
    || turn.getAttribute('data-content-search-unit-key')
    || turn.getAttribute('data-chatgpt-search-unit-key')
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
  if (turn?.matches?.('[data-content-search-unit-key$=":user"], [data-chatgpt-search-unit-key$=":user"]')
      && messageUnitRole(turn) === 'user') {
    return messageUnitText(turn, 'user');
  }
  const users = getMessageUnits('user', turn);
  if (users.length !== 1) return '';
  return messageUnitText(users[0], 'user');
}


async function exactUserTurnsBySubmittedSha256(expectedHash) {
  const hash = String(expectedHash || '').trim().toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(hash)) return [];
  const matches = [];
  for (const turn of getConversationTurns()) {
    const rendered = turnUserText(turn);
    if (!rendered || rendered.length > 12000) continue;
    if (await newChatTextSha256(rendered) === hash) matches.push(turn);
  }
  return matches;
}


function turnCompletionState(turn) {
  return String(turn?.getAttribute?.('data-talvt-turn-state')
    || turn?.querySelector?.('[data-talvt-turn-state]')?.getAttribute('data-talvt-turn-state')
    || '').trim().toLowerCase();
}


function latestConversationTurnHasTerminalProof() {
  const turns = getConversationTurns();
  const turn = turns.length ? turns[turns.length - 1] : null;
  const assistant = lastAssistantNode();
  if (!turn || !assistant) return false;
  if (turn !== assistant && !turn.contains?.(assistant)) return false;
  return turnCompletionState(turn) === 'complete' && hasCompletionAction();
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
    /메시지\s*전송\s*시간이?\s*초과/i,
    /시간이\s*초과되었습니다.*다시\s*시도/i,
    /message\s+(?:sending|send)\s+timed\s+out/i,
    /stream\s+recovery\s+polling\s+timed\s+out/i,
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

    'button[data-testid*="stop" i]',


    'button[aria-label="Stop streaming"]',


    'button[aria-label="Stop"]',

    'button[aria-label*="stop" i]',


    'button[aria-label="\uC911\uC9C0"]',

    'button[aria-label*="\uC911\uC9C0"]',

    'button[aria-label*="\uBA48\uCDA4"]',


    'button[aria-label*="\uC751\uB2F5 \uC911\uC9C0"]'


  ];


  // Background tabs can report zero client rects. Generation identity must not


  // depend on visibility; use DOM presence/status instead.


  const stopPresent = stopSelectors.some((selector) => !!document.querySelector(selector));


  const node = lastAssistantNode();


  const streamPresent = !!node && (node.matches('.result-streaming, [data-message-status="streaming"]') ||
    !!node.querySelector('.result-streaming, [data-message-status="streaming"]'));

  if (!stopPresent && !streamPresent) return false;

  // ChatGPT can retain an inert stop/streaming marker after the exact latest
  // turn has completed.  Ignore it only with two independent terminal signals
  // on that same latest turn.  A send arrow or an empty composer is never
  // sufficient to override a genuinely active generation.
  return !latestConversationTurnHasTerminalProof();


}


function currentReasoningObservation() {
  const buttons = Array.from(document.querySelectorAll('button[aria-label]'));
  const selector = buttons.find((button) => {
    const label = String(button.getAttribute('aria-label') || '').trim();
    return /chatgpt/i.test(label) && /model|\uBAA8\uB378/i.test(label);
  });
  if (!selector) {
    return { status: 'UNAVAILABLE', level: '', source: 'chatgpt-model-selector' };
  }
  const exact = selector.querySelector('[data-effort-only="true"]');
  const lines = String(selector.innerText || selector.textContent || '')
    .split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
  const level = String(exact?.textContent || lines.at(-1) || '').trim();
  if (!level || level.length > 32 || /[\r\n\0]/.test(level)) {
    return { status: 'UNAVAILABLE', level: '', source: 'chatgpt-model-selector' };
  }
  return {
    status: 'OBSERVED',
    level,
    source: 'chatgpt-model-selector',
    observedAt: Date.now(),
  };
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
