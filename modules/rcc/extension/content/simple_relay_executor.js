function setEditorText(editor, text) {


  editor.focus();


  if (editor.tagName === 'TEXTAREA') {


    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;


    if (setter) setter.call(editor, text);


    else editor.value = text;


    editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));


    focusEditorAtEnd(editor);
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
  focusEditorAtEnd(editor);


}

function focusEditorAtEnd(editor) {
  if (!editor || editor.isConnected === false) return false;
  editor.focus();
  const focused = document.activeElement === editor || editor.contains?.(document.activeElement);
  if (!focused) return false;
  if (editor.tagName === 'TEXTAREA') {
    const end = String(editor.value || '').length;
    try { editor.setSelectionRange(end, end); } catch (_) { return false; }
    return editor.selectionStart === end && editor.selectionEnd === end;
  }
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(editor);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
  return selection.rangeCount === 1
    && selection.getRangeAt(0).collapsed
    && editor.contains(selection.getRangeAt(0).endContainer);
}

function wakeEditorWithTrailingSpace(editor) {
  if (!focusEditorAtEnd(editor)) return false;
  if (editor.tagName === 'TEXTAREA') {
    const value = String(editor.value || '') + ' ';
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
    if (setter) setter.call(editor, value);
    else editor.value = value;
    editor.dispatchEvent(new InputEvent('input', {
      bubbles: true, inputType: 'insertText', data: ' ',
    }));
    return focusEditorAtEnd(editor);
  }
  const inserted = document.execCommand('insertText', false, ' ');
  if (!inserted) return false;
  editor.dispatchEvent(new InputEvent('input', {
    bubbles: true, inputType: 'insertText', data: ' ',
  }));
  return focusEditorAtEnd(editor);
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
      // ChatGPT can replace the ProseMirror root after the input event. The
      // current editor is still safe to use only when it contains the exact
      // normalized draft we inserted; object identity is not an effect proof.
      const liveEditor = getEditor();
      if (!liveEditor ||
          editorDraftText(liveEditor) !== RelayCore.normalizeMessageText(options.expectedText)) return null;
      return findReadySendButton(liveEditor, options);
    }
    if (getEditor() !== editor) return null;
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
  const waitMs = Math.max(0, Math.min(8000, Number(options?.waitMs ?? 8000)));
  const expected = typeof options?.expectedText === 'string'
    ? RelayCore.normalizeMessageText(options.expectedText) : null;
  const currentVerifiedEditor = () => {
    const liveEditor = getEditor();
    if (expected === null) return liveEditor === editor ? editor : null;
    return liveEditor && editorDraftText(liveEditor) === expected ? liveEditor : null;
  };
  if (isGenerating()) throw new Error('RELAY_TARGET_GENERATING');
  let liveEditor = getEditor();
  if (!liveEditor || !focusEditorAtEnd(liveEditor)) {
    throw new Error('RELAY_EDITOR_FOCUS_OR_CARET_INVALID');
  }
  if (currentVerifiedEditor() && !findReadySendButton(liveEditor, options)
      && options?.composerWakeMode === 'trailing_space_once') {
    if (!wakeEditorWithTrailingSpace(liveEditor)) {
      throw new Error('RELAY_EDITOR_WAKE_FAILED');
    }
    liveEditor = currentVerifiedEditor();
    if (!liveEditor) throw new Error('RELAY_EDITOR_TEXT_MISMATCH');
  }
  // execCommand and ChatGPT's controlled ProseMirror update do not always
  // settle in the same task.  The draft can be transiently unreadable here
  // and become the exact expected paragraphs before the send button is ready.
  // Keep the exact-text fence, but let the existing bounded observer wait for
  // both the settled draft and the enabled button instead of failing early.
  // Wait for ChatGPT to swap its empty-composer voice control for the enabled send arrow.
  const button = await waitForReadySendButton(editor, waitMs, options);
  if (button) {
    if (isGenerating()) throw new Error('RELAY_TARGET_GENERATING');
    liveEditor = currentVerifiedEditor();
    if (!liveEditor) throw new Error('RELAY_EDITOR_TEXT_MISMATCH');
    // A React render may replace or disable the button after the observer resolved.
    if (findReadySendButton(liveEditor, options) !== button) throw new Error('RELAY_SEND_BUTTON_CHANGED');
    const bindingAttestation = typeof options?.beforeSubmit === 'function'
      ? await options.beforeSubmit() : null;
    if (isGenerating()) throw new Error('RELAY_TARGET_GENERATING');
    liveEditor = currentVerifiedEditor();
    if (!liveEditor) throw new Error('RELAY_EDITOR_TEXT_MISMATCH');
    if (findReadySendButton(liveEditor, options) !== button) throw new Error('RELAY_SEND_BUTTON_CHANGED');
    const activationAttestation = typeof options?.beforeActivation === 'function'
      ? (await options.beforeActivation(bindingAttestation)) || bindingAttestation
      : bindingAttestation;
    if (isGenerating()) throw new Error('RELAY_TARGET_GENERATING');
    liveEditor = currentVerifiedEditor();
    if (!liveEditor || !focusEditorAtEnd(liveEditor)) {
      throw new Error('RELAY_EDITOR_FOCUS_OR_CARET_INVALID');
    }
    if (findReadySendButton(liveEditor, options) !== button) throw new Error('RELAY_SEND_BUTTON_CHANGED');
    const readyAt = Date.now();
    button.click();
    return { ok: true, method: 'send-button', readyAt, clickedAt: Date.now(),
      bindingAttestation: activationAttestation };
  }
  liveEditor = currentVerifiedEditor();
  if (!liveEditor) throw new Error('RELAY_EDITOR_TEXT_MISMATCH');

  if (!allowKeyboardFallback) {
    throw new Error('RELAY_SEND_BUTTON_NOT_READY');
  }

  // Existing-conversation relay keeps a bounded keyboard fallback. Provider
  // bootstrap must disable it because synthetic Enter on ChatGPT's new-chat
  // route can become ?prompt-textarea=... instead of sending a user turn.
  const bindingAttestation = typeof options?.beforeSubmit === 'function'
    ? await options.beforeSubmit() : null;
  liveEditor = currentVerifiedEditor();
  if (!liveEditor) throw new Error('RELAY_EDITOR_TEXT_MISMATCH');
  const activationAttestation = typeof options?.beforeActivation === 'function'
    ? (await options.beforeActivation(bindingAttestation)) || bindingAttestation
    : bindingAttestation;
  if (isGenerating()) throw new Error('RELAY_TARGET_GENERATING');
  if (!focusEditorAtEnd(liveEditor)) throw new Error('RELAY_EDITOR_FOCUS_OR_CARET_INVALID');
  for (const type of ['keydown', 'keypress', 'keyup']) {
    liveEditor.dispatchEvent(new KeyboardEvent(type, {
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
    // ProseMirror renders inserted newlines as adjacent paragraphs.  A blank
    // paragraph is <p><br></p>; its innerText is a layout newline even though
    // its logical text is empty.  Join direct block textContent so one blank
    // paragraph reconstructs exactly one blank source line instead of adding
    // an extra browser-layout newline at the pre-submit fence.
    const children = Array.from(editor.children || []);
    const paragraphDraft = children.length > 0
      && children.every((node) => ['P', 'DIV'].includes(String(node.tagName || '').toUpperCase()));
    raw = paragraphDraft
      ? children.map((node) => node.textContent || '').join('\n')
      : (editor.innerText || editor.textContent || '');
  }
  return RelayCore.normalizeMessageText(raw);
}

function waitForExactUserSubmission(record, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let observer = null;
    let timer = null;
    const finish = (error, turnKey = '') => {
      if (settled) return;
      settled = true;
      try { observer?.disconnect(); } catch (_) {}
      if (timer) clearTimeout(timer);
      error ? reject(error) : resolve(turnKey);
    };
    const check = () => {
      const routed = resolveRoutedTurn(record);
      if (routed.ok && routed.turnKey) finish(null, routed.turnKey);
      else if (routed.terminal) finish(new Error(routed.reason || 'RELAY_EXACT_USER_TURN_REJECTED'));
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

  if (isGenerating()) throw new Error('RELAY_TARGET_GENERATING');

  if (editorDraftText(editor)) throw new Error('RELAY_COMPOSER_NOT_EMPTY');


  const beforeCount = getAssistantNodes().length;


  const beforeText = lastAssistantText();

  setEditorText(editor, text);


  const isNewChatBootstrap = tracking?.bootstrapCreatedTab === true;
  const submitPolicy = tracking?.submitPolicy && typeof tracking.submitPolicy === 'object'
    ? tracking.submitPolicy : {};
  try {
    await submitEditor(editor, {
      expectedText: text,
      // On ChatGPT's blank route a synthetic Enter can become a URL query
      // instead of an actual user turn. New-chat bootstrap therefore accepts
      // only the verified send button; existing-conversation relay keeps its
      // bounded keyboard fallback for compatibility.
      allowKeyboardFallback: isNewChatBootstrap
        ? false : submitPolicy.allowKeyboardFallback !== false,
      composerWakeMode: String(submitPolicy.composerWakeMode || 'none'),
      waitMs: submitPolicy.sendButtonWaitMs,
    });
  } catch (error) {
    // A provider event handler can consume the exact draft and create the user
    // turn before the synthetic click/keyboard call reports an error.  The
    // vanished draft is therefore not proof of failure.  First look for the
    // one exact new user turn fenced by this operation; only an exact DOM
    // match promotes the effect.  This closes the old
    // RELAY_DRAFT_CLEAR_UNPROVEN false-UNKNOWN without clicking twice.
    const liveEditor = getEditor();
    const expectedDraft = RelayCore.normalizeMessageText(text);
    if (!liveEditor || editorDraftText(liveEditor) !== expectedDraft) {
      if (tracking?.relayId && Array.isArray(tracking.beforeTurnKeys)) {
        const recovered = {
          ...tracking,
          relayId: tracking.relayId,
          conversationKey: currentConversationKey(),
          beforeCount,
          beforeText,
          phase: 'submit-activated',
          submittedAt: Date.now(),
        };
        try {
          const routeTurnKey = await waitForExactUserSubmission(recovered, 2000);
          recovered.routeTurnKey = routeTurnKey;
          recovered.phase = 'submitted';
          saveRelayExecution(recovered);
          return { submitted: true, beforeCount, beforeText,
            recoveredAfterSubmitError: true };
        } catch (_) {}
      }
      throw new Error('RELAY_DRAFT_CLEAR_UNPROVEN');
    }
    setEditorText(liveEditor, '');
    const clearedEditor = getEditor();
    if (!clearedEditor || editorDraftText(clearedEditor)) {
      throw new Error('RELAY_DRAFT_CLEAR_UNPROVEN');
    }
    throw error;
  }

  const submittedAt = Date.now();
  const activatedRecord = tracking?.relayId ? {
    ...tracking,
    relayId: tracking.relayId,
    conversationKey: currentConversationKey(),
    beforeCount,
    beforeText,
    phase: 'submit-activated',
    submittedAt,
  } : null;
  if (activatedRecord) saveRelayExecution(activatedRecord);

  const routeTurnKey = await waitForExactUserSubmission(activatedRecord || tracking);

  if (activatedRecord) saveRelayExecution({
    ...activatedRecord,
    routeTurnKey,
    phase: 'submitted',
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
  const composerWakeMode = String(message?.composerWakeMode || 'none');
  const sendButtonWaitMs = Number(message?.sendButtonWaitMs ?? 1000);
  if (!relayId || !expectedConversationKey || !text || text.length > 12000) {
    return { ok: false, submitted: false, effectState: 'NOT_APPLIED', error: 'SIMPLE_RELAY_ARGUMENT_INVALID' };
  }
  if (!['none', 'trailing_space_once'].includes(composerWakeMode)
      || !Number.isInteger(sendButtonWaitMs) || sendButtonWaitMs < 0
      || sendButtonWaitMs > 8000) {
    return { ok: false, submitted: false, effectState: 'NOT_APPLIED',
      error: 'SIMPLE_RELAY_SUBMIT_POLICY_INVALID' };
  }
  if (currentConversationKey() !== expectedConversationKey) {
    return { ok: false, submitted: false, effectState: 'NOT_APPLIED', error: 'SIMPLE_RELAY_CONVERSATION_MISMATCH' };
  }
  const prior = loadRelayExecution();
  if (prior?.relayId === relayId) {
    if (prior.conversationKey !== expectedConversationKey
        || prior.submittedText !== RelayCore.normalizeMessageText(text)) {
      return { ok: false, submitted: false, effectState: 'NOT_APPLIED',
        error: 'SIMPLE_RELAY_OPERATION_ID_REUSE_MISMATCH' };
    }
    const routed = resolveRoutedTurn(prior);
    if (routed.ok && routed.turnKey) {
      prior.routeTurnKey = routed.turnKey;
      prior.phase = 'submitted';
      saveRelayExecution(prior);
      return { ok: true, submitted: true, replayed: true, relayId,
        conversationKey: expectedConversationKey,
        beforeAssistantCount: Number(prior.beforeCount || 0) };
    }
    // The same id reached the activation boundary but its exact user turn is
    // not currently provable. Never overwrite the page record or click again.
    return { ok: false, submitted: false, effectState: 'UNKNOWN',
      error: 'SIMPLE_RELAY_PRIOR_EFFECT_UNRESOLVED' };
  }
  try {
    const record = {
      relayId,
      conversationKey: expectedConversationKey,
      submittedText: RelayCore.normalizeMessageText(text),
      beforeTurnKeys: getConversationTurns().map(turnIdentity).filter(Boolean),
      routeTurnKey: '',
      submitPolicy: {
        allowKeyboardFallback: false,
        composerWakeMode,
        sendButtonWaitMs,
      },
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
    const code = String(error?.message || error || 'SIMPLE_RELAY_SUBMIT_FAILED');
    const notApplied = [
      'RELAY_TARGET_GENERATING', 'Target ChatGPT tab is already generating',
      'RELAY_COMPOSER_NOT_EMPTY', 'RELAY_SEND_BUTTON_NOT_READY',
      'RELAY_EDITOR_FOCUS_OR_CARET_INVALID', 'RELAY_EDITOR_WAKE_FAILED',
      'RELAY_EDITOR_TEXT_MISMATCH', 'RELAY_SEND_BUTTON_CHANGED',
    ].includes(code);
    return { ok: false, submitted: false,
      effectState: notApplied ? 'NOT_APPLIED' : 'UNKNOWN', error: code };
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

async function newChatTextSha256(value) {
  const digest = await crypto.subtle.digest(
    'SHA-256', new TextEncoder().encode(String(value || '')),
  );
  return Array.from(new Uint8Array(digest), (item) =>
    item.toString(16).padStart(2, '0')).join('');
}

// Bootstrap exactly one blank ChatGPT tab. The record is stored before the
// click because ChatGPT replaces the blank document while assigning /c/<uuid>.
// sessionStorage survives that same-origin navigation, so the replacement
// document can prove the exact first user turn without a second submission.
async function executeNewChatBootstrap(message) {
  const relayId = String(message?.relayId || '').trim();
  const text = String(message?.text || '');
  const textSha256 = String(message?.textSha256 || '').trim();
  if (!relayId || !text || text.length > 12000
      || !/^[a-f0-9]{64}$/.test(textSha256)
      || await newChatTextSha256(text) !== textSha256) {
    return { ok: false, submitted: false, effectState: 'NOT_APPLIED',
      error: 'NEW_CHAT_BOOTSTRAP_ARGUMENT_INVALID' };
  }
  if (currentConversationKey() || getMessageUnits('user').length
      || getConversationTurns().length) {
    return { ok: false, submitted: false, effectState: 'NOT_APPLIED',
      error: 'NEW_CHAT_BOOTSTRAP_TAB_NOT_BLANK' };
  }
  const prior = loadRelayExecution();
  if (prior?.relayId) {
    if (prior.relayId === relayId && prior.requestTextSha256 === textSha256) {
      return { ok: true, submitted: prior.phase !== 'submit-intent', replayed: true,
        relayId, conversationKey: String(prior.conversationKey || '') };
    }
    return { ok: false, submitted: false, effectState: 'NOT_APPLIED',
      error: 'NEW_CHAT_BOOTSTRAP_TAB_BUSY' };
  }
  const record = {
    relayId,
    conversationKey: '',
    submittedText: RelayCore.normalizeMessageText(text),
    requestTextSha256: textSha256,
    beforeTurnKeys: [],
    routeTurnKey: '',
    bootstrapCreatedTab: true,
    phase: 'submit-intent',
  };
  saveRelayExecution(record);
  try {
    const submission = await sendPrompt(text, record, false);
    const persisted = loadRelayExecution() || record;
    persisted.requestTextSha256 = textSha256;
    persisted.bootstrapCreatedTab = true;
    saveRelayExecution(persisted);
    return { ok: true, submitted: true, relayId,
      conversationKey: String(persisted.conversationKey || currentConversationKey() || ''),
      beforeAssistantCount: Number(submission?.beforeCount || 0) };
  } catch (error) {
    const persisted = loadRelayExecution();
    const mayHaveSubmitted = persisted?.relayId === relayId
      && ['submit-activated', 'submitted'].includes(String(persisted.phase || ''));
    return { ok: false, submitted: false,
      effectState: mayHaveSubmitted ? 'UNKNOWN' : 'NOT_APPLIED',
      error: String(error?.message || error || 'NEW_CHAT_BOOTSTRAP_FAILED') };
  }
}

async function readNewChatBootstrapStatus(message) {
  const relayId = String(message?.relayId || '').trim();
  const textSha256 = String(message?.textSha256 || '').trim();
  const record = loadRelayExecution();
  if (!relayId || record?.relayId !== relayId
      || record?.requestTextSha256 !== textSha256
      || record?.bootstrapCreatedTab !== true) {
    return { ok: false, effectState: 'NOT_APPLIED',
      error: 'NEW_CHAT_BOOTSTRAP_RECORD_MISSING' };
  }
  const conversationKey = currentConversationKey();
  if (!conversationKey) {
    return { ok: true, submitted: false, completed: false, conversationKey: '' };
  }
  const routed = resolveRoutedTurn(record);
  if (!routed.ok || !routed.turnKey) {
    return { ok: true, submitted: false, completed: false, conversationKey,
      pendingReason: String(routed.reason || 'NEW_CHAT_ROUTE_PENDING') };
  }
  record.conversationKey = conversationKey;
  record.routeTurnKey = routed.turnKey;
  record.phase = 'submitted';
  saveRelayExecution(record);
  if (turnIsGenerating(routed.turn) || isGenerating()) {
    return { ok: true, submitted: true, completed: false, conversationKey };
  }
  try {
    const reply = recoverCompletedReplyFromDom(record);
    record.phase = 'completed';
    saveRelayExecution(record);
    return { ok: true, submitted: true, completed: true,
      conversationKey, reply };
  } catch (error) {
    return { ok: true, submitted: true, completed: false, conversationKey,
      pendingReason: String(error?.message || error || 'NEW_CHAT_REPLY_PENDING') };
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
