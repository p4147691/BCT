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
