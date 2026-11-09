let renameReceiptMutationChain = Promise.resolve();

function renameResultError(code, state = 'NOT_APPLIED') {
  return {
    ok: false,
    state,
    effectState: state,
    ambiguous: state === 'UNKNOWN',
    error: String(code || 'RENAME_FAILED').slice(0, 128),
  };
}

function renameFingerprint(conversationKey, tabId, sessionId, title) {
  return JSON.stringify([conversationKey, tabId, sessionId, title]);
}

async function writeRenameReceipt(operationId, receipt) {
  const state = await loadState();
  const receipts = { ...(state.renameReceipts || {}), [operationId]: receipt };
  await stateRepository.setLocal({ [RENAME_RECEIPTS_KEY]: receipts });
  return receipt;
}

async function exactRenameTab(tabId, conversationKey) {
  let tab;
  try {
    tab = await browserGateway.getExactTab(tabId);
  } catch (_) {
    throw new Error('RENAME_TAB_NOT_OPEN');
  }
  if (!isChatTab(tab)) throw new Error('RENAME_TAB_NOT_CHATGPT');
  if (RelayCore.conversationKey(String(tab.url || '')) !== conversationKey) {
    throw new Error('RENAME_TAB_CONVERSATION_MISMATCH');
  }
  return tab;
}

function dotKeyFromUrl(value) {
  try {
    const url = new URL(String(value || ''));
    if (!/^(?:chatgpt\.com|chat\.openai\.com)$/i.test(url.hostname)) return '';
    return url.pathname.match(/^\/dots\/([A-Za-z0-9_-]{1,160}~[A-Za-z0-9_-]{1,160})\/?$/)?.[1] || '';
  } catch (_) {
    return '';
  }
}

async function exactDotRenameTab(tabId, dotKey) {
  let tab;
  try {
    tab = await browserGateway.getExactTab(tabId);
  } catch (_) {
    throw new Error('DOT_RENAME_TAB_NOT_OPEN');
  }
  if (!isChatTab(tab)) throw new Error('DOT_RENAME_TAB_NOT_CHATGPT');
  if (dotKeyFromUrl(tab.url) !== dotKey) throw new Error('DOT_RENAME_TAB_IDENTITY_MISMATCH');
  return tab;
}

function observedChatTitle(tab) {
  return String(tab?.title || '').trim()
    .replace(/\s*(?:[-–—|·]\s*)?ChatGPT\s*$/i, '').trim();
}

function dotRenameSatisfiedResult({ operationId, title, tabId, dotKey, sessionId, reconciled = false }) {
  return {
    ok: true, state: 'APPLIED', effectState: 'APPLIED', ambiguous: false,
    operationId, savedTitle: title, tabId, dotKey, sessionId,
    noUiEffect: true, reconciled,
  };
}

async function executeDotRenameInMainWorld(tabId, operationId, dotKey, title) {
  const injected = await browserGateway.executeScript({
    target: { tabId },
    world: 'MAIN',
    func: async (request) => {
      const diagnostic = {
        version: 1, world: 'MAIN', identity: 'MATCH', route: 'PROFILE_CUSTOMIZER',
        profile: 'NOT_FOUND', customizer: 'NOT_FOUND', nameControl: 'NOT_FOUND',
        editor: 'NOT_FOUND', innerSave: 'NOT_ATTEMPTED', outerSave: 'NOT_ATTEMPTED',
      };
      const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
      const visible = (node) => {
        if (!node || !node.getClientRects?.().length) return false;
        const rect = node.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        const style = getComputedStyle(node);
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity || 1) !== 0;
      };
      const semantic = (node) => normalize([
        node?.getAttribute?.('aria-label'), node?.getAttribute?.('title'),
        node?.getAttribute?.('data-testid'), node?.textContent,
      ].filter(Boolean).join(' '));
      const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
      const wait = async (find, timeoutMs = 5000) => {
        const deadline = Date.now() + timeoutMs;
        while (Date.now() < deadline) {
          const value = find();
          if (value) return value;
          await sleep(100);
        }
        return null;
      };
      const dotKeyAt = (value = location.href) => {
        try {
          const url = new URL(String(value || ''), location.href);
          if (!/^(?:chatgpt\.com|chat\.openai\.com)$/i.test(url.hostname)) return '';
          return url.pathname.match(/^\/dots\/([A-Za-z0-9_-]{1,160}~[A-Za-z0-9_-]{1,160})\/?$/)?.[1] || '';
        } catch (_) {
          return '';
        }
      };
      const pageTitle = () => normalize(String(document.title || '')
        .replace(/\s*(?:[-–—|·]\s*)?ChatGPT\s*$/i, ''));
      const exactTitleLeaves = (scope, value) => Array.from(scope.querySelectorAll?.('*') || [])
        .filter((node) => visible(node) && normalize(node.textContent) === value)
        .filter((node) => !Array.from(node.children || []).some((child) =>
          normalize(child.textContent) === value));
      const saveButton = (scope) => Array.from(scope?.querySelectorAll?.('button') || [])
        .find((button) => visible(button) && !button.disabled &&
          (/^(?:save|저장|confirm|확인)$/i.test(semantic(button)) || button.type === 'submit')) || null;
      const customizer = (currentTitle) => {
        const hasTitle = (scope) => exactTitleLeaves(scope, currentTitle).length > 0;
        const hasSave = (scope) => Array.from(scope.querySelectorAll?.('button') || [])
          .some((button) => visible(button) && /^(?:save|저장)$/i.test(semantic(button)));
        const explicit = Array.from(document.querySelectorAll(
          '[role="dialog"], [aria-modal="true"], [data-radix-dialog-content]'
        )).filter((scope) => visible(scope) && hasTitle(scope) && hasSave(scope));
        if (explicit.length === 1) return explicit[0];
        const scopes = [];
        for (const leaf of exactTitleLeaves(document, currentTitle)) {
          let scope = leaf.parentElement;
          for (let depth = 0; scope && depth < 12; depth += 1, scope = scope.parentElement) {
            if (scope === document.body || scope === document.documentElement) break;
            if (visible(scope) && hasSave(scope)) { scopes.push(scope); break; }
          }
        }
        return scopes.length === 1 ? scopes[0] : null;
      };
      const profileTitle = (currentTitle) => {
        const controls = Array.from(document.querySelectorAll(
          'main button, main [role="button"], main [tabindex="0"], '
          + '[data-testid*="dot"] button, [data-testid*="dot"] [role="button"]'
        )).filter((node) => visible(node) && !node.disabled &&
          !node.closest?.('nav, [data-testid*="sidebar"]'));
        const exact = controls.filter((node) => semantic(node) === currentTitle);
        if (exact.length === 1) return exact[0];
        const leaves = exactTitleLeaves(document, currentTitle)
          .filter((node) => !node.closest?.('nav, [data-testid*="sidebar"]'));
        const bounded = leaves.filter((leaf) => {
          let scope = leaf.parentElement;
          for (let depth = 0; scope && depth < 7; depth += 1, scope = scope.parentElement) {
            if (/(?:^|\s)(?:active|활성)(?:\s|$)/i.test(semantic(scope))) return true;
          }
          return false;
        });
        return bounded.length === 1 ? bounded[0] : null;
      };
      const editors = () => Array.from(document.querySelectorAll(
        'input:not([type]), input[type="text"], textarea, [contenteditable="true"], [role="textbox"]'
      )).filter((node) => visible(node) && !node.disabled &&
        !/prompt|composer|message|메시지|프롬프트/i.test(semantic(node)));
      const fail = (error, effectState = 'NOT_APPLIED') => ({
        ok: false, effectState, error, operationId: request.operationId, renameDiagnostic: diagnostic,
      });
      let effectStarted = false;
      try {
        if (dotKeyAt() !== request.dotKey) {
          diagnostic.identity = 'MISMATCH';
          return fail('DOT_RENAME_TARGET_STALE');
        }
        const currentTitle = pageTitle();
        if (!currentTitle) return fail('DOT_PROFILE_TITLE_NOT_FOUND');
        let outer = customizer(currentTitle);
        if (!outer) {
          const profile = profileTitle(currentTitle);
          if (!profile) return fail('DOT_PROFILE_TITLE_CONTROL_NOT_FOUND');
          diagnostic.profile = 'FOUND';
          profile.click();
          outer = await wait(() => customizer(currentTitle));
        }
        if (!outer) return fail('DOT_CUSTOMIZATION_DIALOG_NOT_FOUND');
        diagnostic.customizer = 'FOUND';
        const nameLeaves = exactTitleLeaves(outer, currentTitle);
        const controls = Array.from(outer.querySelectorAll?.(
          'button, [role="button"], [tabindex="0"]'
        ) || []).filter((node) => visible(node) && !node.disabled && semantic(node) === currentTitle);
        const nameControl = controls.length === 1 ? controls[0]
          : (nameLeaves.length === 1 ? nameLeaves[0] : null);
        if (!nameControl) return fail('DOT_CUSTOMIZATION_NAME_CONTROL_NOT_FOUND');
        diagnostic.nameControl = 'FOUND';
        const previousEditors = new Set(editors());
        nameControl.click();
        const input = await wait(() => {
          const fresh = editors().filter((node) => !previousEditors.has(node));
          const named = fresh.filter((node) => /name|title|이름|제목/i.test(semantic(node)));
          return named.length === 1 ? named[0] : (fresh.length === 1 ? fresh[0] : null);
        });
        if (!input) return fail('DOT_RENAME_INPUT_NOT_FOUND');
        diagnostic.editor = 'FOUND';
        const previousValue = input.value !== undefined
          ? String(input.value || '') : String(input.textContent || '');
        input.focus();
        input.select?.();
        if (input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement) {
          const proto = input instanceof HTMLTextAreaElement
            ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
          if (setter) setter.call(input, request.title); else input.value = request.title;
          input._valueTracker?.setValue?.(previousValue);
        } else {
          input.textContent = request.title;
        }
        input.dispatchEvent(new InputEvent('beforeinput', {
          bubbles: true, cancelable: true, inputType: 'insertText', data: request.title,
        }));
        input.dispatchEvent(new InputEvent('input', {
          bubbles: true, inputType: 'insertText', data: request.title,
        }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        await sleep(100);
        let innerScope = input.closest?.('[role="dialog"], [aria-modal="true"], [data-radix-dialog-content]')
          || input.closest?.('form') || input.parentElement;
        for (let depth = 0; innerScope && depth < 10 && !saveButton(innerScope); depth += 1) {
          innerScope = innerScope.parentElement;
        }
        const innerSave = await wait(() => saveButton(innerScope));
        if (!innerSave) return fail('DOT_RENAME_INNER_SAVE_NOT_READY');
        diagnostic.innerSave = 'ATTEMPTED';
        effectStarted = true;
        innerSave.focus?.({ preventScroll: true });
        await sleep(50);
        innerSave.click();
        const staged = await wait(() => (!document.contains(input) || !visible(input)) && visible(outer));
        if (!staged) return fail('DOT_RENAME_INNER_SAVE_NOT_VERIFIED', 'UNKNOWN');
        diagnostic.innerSave = 'OBSERVED';
        const outerSave = await wait(() => saveButton(outer));
        if (!outerSave) return fail('DOT_RENAME_OUTER_SAVE_NOT_READY', 'UNKNOWN');
        diagnostic.outerSave = 'ATTEMPTED';
        outerSave.focus?.({ preventScroll: true });
        await sleep(50);
        outerSave.click();
        const accepted = await wait(() => {
          if (dotKeyAt() !== request.dotKey) return false;
          if (pageTitle() === request.title) return true;
          return Array.from(document.querySelectorAll('a[href]')).some((anchor) => {
            try {
              return dotKeyAt(new URL(anchor.href, location.href).href) === request.dotKey &&
                normalize(anchor.textContent) === request.title;
            } catch (_) { return false; }
          });
        }, 8000);
        if (!accepted) return fail('DOT_RENAME_UI_NOT_VERIFIED', 'UNKNOWN');
        return { ok: true, effectState: 'APPLIED', operationId: request.operationId,
          savedTitle: request.title, route: 'PROFILE_CUSTOMIZER', world: 'MAIN' };
      } catch (error) {
        return fail(String(error?.message || error || 'DOT_RENAME_MAIN_WORLD_FAILED'),
          effectStarted ? 'UNKNOWN' : 'NOT_APPLIED');
      }
    },
    args: [{ operationId, dotKey, title }],
  });
  return injected?.[0]?.result || {
    ok: false, effectState: 'UNKNOWN', error: 'DOT_RENAME_MAIN_WORLD_ACK_MISSING', operationId,
  };
}

async function runConversationRename(message, requestId) {
  const operationId = String(message.operationId || requestId || '').trim();
  const conversationKey = String(message.conversationKey || '').trim();
  const sessionId = String(message.sessionId || '').trim();
  const title = String(message.title || '').trim();
  const tabId = Number(message.tabId);
  if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(operationId)) {
    return renameResultError('RENAME_OPERATION_ID_INVALID');
  }
  if (!/^[a-z0-9-]{8,64}$/i.test(conversationKey) || !sessionId ||
      !Number.isSafeInteger(tabId) || tabId <= 0 || !title || title.length > 100) {
    return renameResultError('RENAME_EXACT_IDENTITY_REQUIRED');
  }
  await endpointSessionReady;
  if (sessionId !== endpointSessionId) return renameResultError('RENAME_SESSION_STALE');

  const fingerprint = renameFingerprint(conversationKey, tabId, sessionId, title);
  const state = await loadState();
  const existing = state.renameReceipts?.[operationId] || null;
  if (existing) {
    if (existing.fingerprint !== fingerprint) {
      return renameResultError('RENAME_OPERATION_ID_REUSE_MISMATCH');
    }
    if (existing.terminal === true && existing.result) {
      return { ...existing.result, replayed: true };
    }
    return renameResultError('RENAME_PRIOR_EFFECT_UNRESOLVED', 'UNKNOWN');
  }

  try {
    await exactRenameTab(tabId, conversationKey);
  } catch (error) {
    return renameResultError(error?.message || error);
  }

  const prepared = {
    version: 1,
    terminal: false,
    command: 'rename-conversation',
    fingerprint,
    operationId,
    conversationKey,
    tabId,
    sessionId,
    title,
    state: 'PREPARED',
    updatedAt: Date.now(),
  };
  try {
    await writeRenameReceipt(operationId, prepared);
  } catch (_) {
    return renameResultError('RENAME_RECEIPT_PREPARE_FAILED');
  }

  let reply;
  try {
    reply = await sendToChatTab(tabId, {
      type: 'relay:renameConversation',
      operationId,
      conversationKey,
      title,
    });
  } catch (error) {
    return renameResultError(
      String(error?.message || error || 'RENAME_TRANSPORT_UNKNOWN'), 'UNKNOWN'
    );
  }

  if (reply?.ok === true && reply.savedTitle === title &&
      reply.operationId === operationId) {
    try {
      await exactRenameTab(tabId, conversationKey);
    } catch (_) {
      return renameResultError('RENAME_POST_EFFECT_IDENTITY_UNKNOWN', 'UNKNOWN');
    }
    const result = {
      ok: true,
      state: 'APPLIED',
      effectState: 'APPLIED',
      ambiguous: false,
      operationId,
      savedTitle: title,
      tabId,
      conversationKey,
      sessionId,
    };
    try {
      await writeRenameReceipt(operationId, {
        ...prepared,
        terminal: true,
        state: 'APPLIED',
        result,
        updatedAt: Date.now(),
      });
    } catch (_) {
      return renameResultError('RENAME_TERMINAL_RECEIPT_UNKNOWN', 'UNKNOWN');
    }
    await publishEndpointSnapshot('conversation-renamed').catch(() => null);
    return result;
  }

  const notApplied = reply?.effectState === 'NOT_APPLIED';
  const result = renameResultError(
    reply?.error || 'RENAME_CONTENT_ACK_INVALID',
    notApplied ? 'NOT_APPLIED' : 'UNKNOWN'
  );
  if (reply?.renameDiagnostic && typeof reply.renameDiagnostic === 'object') {
    result.renameDiagnostic = reply.renameDiagnostic;
  }
  await writeRenameReceipt(operationId, {
    ...prepared,
    terminal: notApplied,
    state: result.state,
    result: notApplied ? result : undefined,
    error: result.error,
    updatedAt: Date.now(),
  }).catch(() => null);
  return result;
}

function renameConversation(message, requestId) {
  const run = renameReceiptMutationChain.then(
    () => runConversationRename(message, requestId),
    () => runConversationRename(message, requestId)
  );
  renameReceiptMutationChain = run.then(() => undefined, () => undefined);
  return run;
}

async function runDotRename(message, requestId) {
  const operationId = String(message.operationId || requestId || '').trim();
  const dotKey = String(message.dotKey || '').trim();
  const sessionId = String(message.sessionId || '').trim();
  const title = String(message.title || '').trim();
  const tabId = Number(message.tabId);
  if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(operationId)) {
    return renameResultError('DOT_RENAME_OPERATION_ID_INVALID');
  }
  if (!/^[A-Za-z0-9_-]{1,160}~[A-Za-z0-9_-]{1,160}$/.test(dotKey) || !sessionId ||
      !Number.isSafeInteger(tabId) || tabId <= 0 || !title || title.length > 100) {
    return renameResultError('DOT_RENAME_EXACT_IDENTITY_REQUIRED');
  }
  await endpointSessionReady;
  if (sessionId !== endpointSessionId) return renameResultError('DOT_RENAME_SESSION_STALE');

  const fingerprint = JSON.stringify(['DOT', dotKey, tabId, sessionId, title]);
  const state = await loadState();
  const existing = state.renameReceipts?.[operationId] || null;
  if (existing) {
    if (existing.fingerprint !== fingerprint) {
      return renameResultError('DOT_RENAME_OPERATION_ID_REUSE_MISMATCH');
    }
    if (existing.terminal === true && existing.result) return { ...existing.result, replayed: true };
    // Reconcile the same unresolved set-title operation without dispatching the
    // UI effect again.  If the exact Dot tab already exposes the requested
    // title, the desired state is satisfied regardless of whether ChatGPT
    // treated an earlier same-title Save as a disabled/no-op action.
    const observed = await exactDotRenameTab(tabId, dotKey).catch(() => null);
    if (observed && observedChatTitle(observed) === title) {
      const result = dotRenameSatisfiedResult({
        operationId, title, tabId, dotKey, sessionId, reconciled: true,
      });
      try {
        await writeRenameReceipt(operationId, {
          ...existing, terminal: true, state: 'APPLIED', result, updatedAt: Date.now(),
        });
      } catch (_) {
        return renameResultError('DOT_RENAME_TERMINAL_RECEIPT_UNKNOWN', 'UNKNOWN');
      }
      return result;
    }
    return renameResultError('DOT_RENAME_PRIOR_EFFECT_UNRESOLVED', 'UNKNOWN');
  }

  let exactTab;
  try {
    exactTab = await exactDotRenameTab(tabId, dotKey);
  } catch (error) {
    return renameResultError(error?.message || error);
  }
  const prepared = {
    version: 1, terminal: false, command: 'rename-dot', fingerprint,
    operationId, dotKey, tabId, sessionId, title, state: 'PREPARED', updatedAt: Date.now(),
  };
  try {
    await writeRenameReceipt(operationId, prepared);
  } catch (_) {
    return renameResultError('DOT_RENAME_RECEIPT_PREPARE_FAILED');
  }

  // ChatGPT can disable Save when the title is unchanged.  Treat exact
  // desired-state equality as an applied idempotent no-op instead of opening
  // the editor and later misclassifying the operation as UNKNOWN.
  if (observedChatTitle(exactTab) === title) {
    const result = dotRenameSatisfiedResult({ operationId, title, tabId, dotKey, sessionId });
    try {
      await writeRenameReceipt(operationId, {
        ...prepared, terminal: true, state: 'APPLIED', result, updatedAt: Date.now(),
      });
    } catch (_) {
      return renameResultError('DOT_RENAME_TERMINAL_RECEIPT_UNKNOWN', 'UNKNOWN');
    }
    return result;
  }

  let reply;
  try {
    reply = await executeDotRenameInMainWorld(tabId, operationId, dotKey, title);
  } catch (error) {
    return renameResultError(String(error?.message || error || 'DOT_RENAME_TRANSPORT_UNKNOWN'), 'UNKNOWN');
  }
  if (reply?.ok === true && reply.savedTitle === title && reply.operationId === operationId) {
    try {
      await exactDotRenameTab(tabId, dotKey);
    } catch (_) {
      return renameResultError('DOT_RENAME_POST_EFFECT_IDENTITY_UNKNOWN', 'UNKNOWN');
    }
    const result = {
      ok: true, state: 'APPLIED', effectState: 'APPLIED', ambiguous: false,
      operationId, savedTitle: title, tabId, dotKey, sessionId,
    };
    try {
      await writeRenameReceipt(operationId, {
        ...prepared, terminal: true, state: 'APPLIED', result, updatedAt: Date.now(),
      });
    } catch (_) {
      return renameResultError('DOT_RENAME_TERMINAL_RECEIPT_UNKNOWN', 'UNKNOWN');
    }
    await publishEndpointSnapshot('dot-renamed').catch(() => null);
    return result;
  }
  const notApplied = reply?.effectState === 'NOT_APPLIED';
  const result = renameResultError(
    reply?.error || 'DOT_RENAME_CONTENT_ACK_INVALID', notApplied ? 'NOT_APPLIED' : 'UNKNOWN'
  );
  if (reply?.renameDiagnostic && typeof reply.renameDiagnostic === 'object') {
    result.renameDiagnostic = reply.renameDiagnostic;
  }
  await writeRenameReceipt(operationId, {
    ...prepared, terminal: notApplied, state: result.state,
    result: notApplied ? result : undefined, error: result.error, updatedAt: Date.now(),
  }).catch(() => null);
  return result;
}

function renameDot(message, requestId) {
  const run = renameReceiptMutationChain.then(
    () => runDotRename(message, requestId),
    () => runDotRename(message, requestId)
  );
  renameReceiptMutationChain = run.then(() => undefined, () => undefined);
  return run;
}
