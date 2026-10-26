// Atomic Chrome-chat actions share the durable new-chat receipt store with
// the composite flow, but never invoke the composite command.  Creation,
// movement, and first submission are independently observable operations.

function atomicChatOperationId(value) {
  return newChatOperationId(value);
}

function atomicPositiveId(value, code) {
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < 1) throw new Error(code);
  return number;
}

async function atomicChatEndpoint(message) {
  await endpointSessionReady;
  const state = await loadState();
  const instanceId = String(state.settings?.instanceId || '');
  if (!instanceId || String(message.instanceId || '') !== instanceId) {
    throw new Error('ATOMIC_CHAT_INSTANCE_ID_MISMATCH');
  }
  // Creation starts from the extension's current endpoint session; callers
  // cannot know that session until the creation receipt is returned.  All
  // later actions must echo it and are rejected if it changed.
  const suppliedSessionId = String(message.sessionId || '').trim();
  const sessionId = suppliedSessionId || endpointSessionId;
  if (!sessionId || (suppliedSessionId && sessionId !== endpointSessionId)) {
    throw new Error('ATOMIC_CHAT_SESSION_ID_MISMATCH');
  }
  return { instanceId, sessionId };
}

function atomicCreationPublic(receipt, replayed = false) {
  const complete = receipt?.state === 'PENDING_UNBOUND';
  return {
    ok: complete,
    command: String(receipt?.command || ''),
    operationId: String(receipt?.operationId || ''),
    state: String(receipt?.state || 'UNKNOWN'),
    effectState: complete ? 'APPLIED_CONFIRMED'
      : receipt?.state === 'NOT_APPLIED' ? 'NOT_APPLIED' : 'UNKNOWN',
    replayed,
    instanceId: String(receipt?.instanceId || ''),
    sessionId: String(receipt?.sessionId || ''),
    tabId: Number(receipt?.tabId) || null,
    windowId: Number(receipt?.windowId) || null,
    conversationKey: '',
    bindingState: complete ? 'PENDING_UNBOUND' : 'UNKNOWN',
    creationReceipt: complete ? {
      operationId: String(receipt?.operationId || ''),
      instanceId: String(receipt?.instanceId || ''),
      sessionId: String(receipt?.sessionId || ''),
      tabId: Number(receipt?.tabId) || null,
      windowId: Number(receipt?.windowId) || null,
      conversationKey: '', bindingState: 'PENDING_UNBOUND',
    } : null,
    error: complete ? '' : String(receipt?.error || receipt?.state || 'UNKNOWN'),
  };
}

async function rememberAtomicCreation(command, message, invoke) {
  const operationId = atomicChatOperationId(message.operationId || message.requestId);
  const endpoint = await atomicChatEndpoint(message);
  const requestedWindowId = command === 'create-chat-tab' && message.windowId != null
    ? atomicPositiveId(message.windowId, 'ATOMIC_CHAT_WINDOW_ID_INVALID') : null;
  const fingerprint = JSON.stringify([
    command, endpoint.instanceId, endpoint.sessionId, requestedWindowId,
  ]);
  const existing = (await readNewChatReceipts())[operationId] || null;
  if (existing) {
    if (existing.command !== command || existing.fingerprint !== fingerprint) {
      throw new Error('ATOMIC_CHAT_OPERATION_ID_REUSE_MISMATCH');
    }
    return atomicCreationPublic(existing, true);
  }

  const result = await invoke({ operationId, ...endpoint, requestedWindowId });
  const receipt = await writeNewChatReceipt(operationId, {
    command, fingerprint, instanceId: endpoint.instanceId, sessionId: endpoint.sessionId,
    requestedWindowId, state: String(result?.state || 'CREATE_UNKNOWN'),
    tabId: Number(result?.tabId) || null, windowId: Number(result?.windowId) || null,
    creationReceipt: result?.creationReceipt || null,
    error: String(result?.error || ''),
    stageTiming: { beganAt: Date.now(), createFinishedAt: Date.now() },
  });
  return atomicCreationPublic(receipt);
}

async function createAtomicChatTab(message) {
  return rememberAtomicCreation('create-chat-tab', message, (intent) =>
    getTabCreateAdapter().createTab({
      operationId: intent.operationId, instanceId: intent.instanceId,
      sessionId: intent.sessionId, requestedWindowId: intent.requestedWindowId,
      conversationKey: '',
    }));
}

async function createAtomicChatWindow(message) {
  return rememberAtomicCreation('create-chat-window', message, (intent) =>
    getWindowCreateAdapter().createWindow({
      operationId: intent.operationId, instanceId: intent.instanceId,
      sessionId: intent.sessionId, conversationKey: '',
    }));
}

function publicCreatedTabBootstrapResult(receipt, replayed = false) {
  const complete = receipt?.state === 'RESULT_PERSISTED';
  return {
    ...publicNewChatResult(receipt, replayed),
    id: String(receipt?.operationId || ''),
    command: 'send-to-created-tab',
    ambiguous: !complete,
    fingerprint: String(receipt?.fingerprint || ''),
  };
}

async function sendToAtomicCreatedTab(message) {
  const operationId = atomicChatOperationId(message.operationId || message.requestId);
  const createOperationId = atomicChatOperationId(message.createOperationId);
  const endpoint = await atomicChatEndpoint(message);
  const tabId = atomicPositiveId(message.tabId, 'ATOMIC_CHAT_TAB_ID_INVALID');
  const windowId = atomicPositiveId(message.windowId, 'ATOMIC_CHAT_WINDOW_ID_INVALID');
  const text = newChatText(message.text);
  const timeoutMs = Math.max(15000, Math.min(360000, Number(message.responseTimeoutMs || 300000)));
  const fingerprint = JSON.stringify([
    createOperationId, endpoint.instanceId, endpoint.sessionId, tabId, windowId, text,
  ]);
  const receipts = await readNewChatReceipts();
  const existing = receipts[operationId] || null;
  if (existing) {
    if (existing.command !== 'send-to-created-tab' || existing.fingerprint !== fingerprint) {
      throw new Error('ATOMIC_CHAT_OPERATION_ID_REUSE_MISMATCH');
    }
    if (existing.state === 'RESULT_PERSISTED' || existing.state === 'NOT_APPLIED'
        || existing.state === 'SUBMIT_UNKNOWN') {
      return publicCreatedTabBootstrapResult(existing, true);
    }
    return publicCreatedTabBootstrapResult(
      await collectNewChatResult(existing, Date.now() + timeoutMs), true,
    );
  }
  const creation = receipts[createOperationId] || null;
  if (!creation || !['create-chat-tab', 'create-chat-window'].includes(creation.command)
      || creation.state !== 'PENDING_UNBOUND'
      || creation.instanceId !== endpoint.instanceId || creation.sessionId !== endpoint.sessionId
      || Number(creation.tabId) !== tabId || Number(creation.windowId) !== windowId) {
    throw new Error('ATOMIC_CHAT_CREATION_RECEIPT_MISMATCH');
  }
  const live = await newChatLiveTab({ tabId, windowId });
  if (RelayCore.conversationKey(String(live.url || ''))) {
    throw new Error('ATOMIC_CHAT_CREATED_TAB_ALREADY_BOUND');
  }
  let receipt = await writeNewChatReceipt(operationId, {
    command: 'send-to-created-tab', fingerprint, createOperationId,
    state: 'SUBMIT_INTENT', instanceId: endpoint.instanceId, sessionId: endpoint.sessionId,
    tabId, windowId, textSha256: await relaySha256(text),
    stageTiming: { beganAt: Date.now(), submitAttemptedAt: Date.now() },
  });
  try {
    const execution = await browserGateway.sendWithReceiver(tabId, {
      type: 'relay:newChatExecute', relayId: operationId, text, textSha256: receipt.textSha256,
    });
    if (execution?.effectState === 'NOT_APPLIED' && execution?.submitted === false) {
      receipt = await writeNewChatReceipt(operationId, {
        ...receipt, state: 'NOT_APPLIED', error: String(execution.error || 'NEW_CHAT_SURFACE_NOT_APPLIED'),
        surfaceKind: String(execution.surfaceKind || ''),
        surfaceEvidence: execution.surfaceEvidence || null,
      });
      return publicCreatedTabBootstrapResult(receipt);
    }
  } catch (_) {
    // Navigation after submission is expected.  Reconcile only this receipt.
  }
  return publicCreatedTabBootstrapResult(
    await collectNewChatResult(receipt, Date.now() + timeoutMs),
  );
}

async function moveAtomicChatTab(message) {
  const operationId = atomicChatOperationId(message.operationId || message.requestId);
  const endpoint = await atomicChatEndpoint(message);
  const tabId = atomicPositiveId(message.tabId, 'ATOMIC_CHAT_TAB_ID_INVALID');
  const expectedWindowId = atomicPositiveId(message.windowId, 'ATOMIC_CHAT_WINDOW_ID_INVALID');
  const targetWindowId = atomicPositiveId(message.targetWindowId, 'ATOMIC_CHAT_TARGET_WINDOW_ID_INVALID');
  const requestedIndex = Number(message.index);
  const conversationKey = String(message.conversationKey || '').trim();
  const createOperationId = String(message.createOperationId || '').trim();
  if (!Number.isSafeInteger(requestedIndex) || requestedIndex < -1
      || (!!conversationKey) === (!!createOperationId)) {
    throw new Error('ATOMIC_CHAT_MOVE_IDENTITY_REQUIRED');
  }
  if (conversationKey && !/^[a-f0-9-]{8,64}$/i.test(conversationKey)) {
    throw new Error('ATOMIC_CHAT_CONVERSATION_KEY_INVALID');
  }
  if (createOperationId) {
    const creation = (await readNewChatReceipts())[createOperationId] || null;
    if (!creation || !['create-chat-tab', 'create-chat-window'].includes(creation.command)
        || creation.state !== 'PENDING_UNBOUND' || creation.instanceId !== endpoint.instanceId
        || creation.sessionId !== endpoint.sessionId || Number(creation.tabId) !== tabId
        || Number(creation.windowId) !== expectedWindowId) {
      throw new Error('ATOMIC_CHAT_CREATION_RECEIPT_MISMATCH');
    }
  }
  const fingerprint = JSON.stringify([
    tabId, expectedWindowId, targetWindowId, requestedIndex, conversationKey, createOperationId,
  ]);
  const existing = (await readNewChatReceipts())[operationId] || null;
  if (existing) {
    if (existing.command !== 'move-tab' || existing.fingerprint !== fingerprint) {
      throw new Error('ATOMIC_CHAT_OPERATION_ID_REUSE_MISMATCH');
    }
    return { ...existing.result, replayed: true };
  }
  const result = await getTabMoveAdapter().move({
    operationId, tabId, expectedWindowId, targetWindowId, requestedIndex,
    conversationKey, expectBlankConversation: !!createOperationId,
  });
  await writeNewChatReceipt(operationId, {
    command: 'move-tab', fingerprint, instanceId: endpoint.instanceId, sessionId: endpoint.sessionId,
    state: String(result.state || 'MOVE_UNKNOWN'), result, error: String(result.error || ''),
  });
  return result;
}
