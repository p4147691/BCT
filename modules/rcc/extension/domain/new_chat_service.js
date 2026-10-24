let newChatReceiptMutationChain = Promise.resolve();

function withNewChatReceiptMutation(mutation) {
  const next = newChatReceiptMutationChain.then(mutation, mutation);
  newChatReceiptMutationChain = next.catch(() => {});
  return next;
}

async function readNewChatReceipts() {
  const data = await stateRepository.getLocal(NEW_CHAT_RECEIPTS_KEY);
  const value = data[NEW_CHAT_RECEIPTS_KEY];
  return value && typeof value === 'object' ? value : {};
}

async function writeNewChatReceipt(operationId, value) {
  return withNewChatReceiptMutation(async () => {
    const receipts = await readNewChatReceipts();
    receipts[operationId] = { ...value, operationId, updatedAt: Date.now() };
    const retained = Object.entries(receipts)
      .sort((a, b) => Number(b[1]?.updatedAt || 0) - Number(a[1]?.updatedAt || 0))
      .slice(0, 32);
    await stateRepository.setLocal({ [NEW_CHAT_RECEIPTS_KEY]: Object.fromEntries(retained) });
    return receipts[operationId];
  });
}

function publicNewChatResult(receipt, replayed = false) {
  const complete = receipt?.state === 'RESULT_PERSISTED';
  return {
    ok: complete,
    command: 'new-chat-send',
    operationId: String(receipt?.operationId || ''),
    state: String(receipt?.state || 'UNKNOWN'),
    effectState: complete ? 'APPLIED_CONFIRMED'
      : receipt?.state === 'NOT_APPLIED' ? 'NOT_APPLIED' : 'UNKNOWN',
    replayed,
    instanceId: String(receipt?.instanceId || ''),
    sessionId: String(receipt?.sessionId || ''),
    tabId: Number(receipt?.tabId) || null,
    windowId: Number(receipt?.windowId) || null,
    conversationKey: String(receipt?.conversationKey || ''),
    textSha256: String(receipt?.textSha256 || ''),
    resultHash: String(receipt?.resultHash || ''),
    resultState: complete ? 'RESULT_PERSISTED' : '',
    reply: complete ? String(receipt?.reply || '') : '',
    surfaceKind: String(receipt?.surfaceKind || ''),
    surfaceEvidence: receipt?.surfaceEvidence || null,
    stageTiming: receipt?.stageTiming || null,
    error: complete ? '' : String(receipt?.error || receipt?.state || 'UNKNOWN'),
  };
}

function publicPersistedNewChatResult(state, operationId) {
  const receipt = state?.newChatReceipts?.[operationId] || null;
  if (!receipt || receipt.state !== 'RESULT_PERSISTED') return null;
  return publicNewChatResult(receipt, true);
}

function publicPendingNewChatStatus(receipt) {
  if (!receipt || ['RESULT_PERSISTED', 'NOT_APPLIED'].includes(
    String(receipt.state || ''),
  )) return null;
  return {
    kind: 'NEW_CHAT',
    state: String(receipt.state || 'UNKNOWN'),
    tabId: Number(receipt.tabId) || null,
    windowId: Number(receipt.windowId) || null,
    requestedWindowId: Number(receipt.requestedWindowId) || null,
    conversationKey: String(receipt.conversationKey || ''),
    textSha256: String(receipt.textSha256 || ''),
    stageTiming: receipt.stageTiming || null,
    error: String(receipt.error || ''),
  };
}

// A persisted new-chat result is the durable authority that its exact browser
// effect finished.  Retire only that same page-session execution record so a
// later Delivery is not mistaken for an overlap with the completed bootstrap.
// The content script independently revalidates the relay ID and completed DOM
// reply before it clears sessionStorage.  Retirement is best-effort: losing
// this cleanup response must never erase or downgrade the persisted result.
async function retirePersistedNewChatExecution(receipt) {
  if (!receipt || receipt.state !== 'RESULT_PERSISTED'
      || !String(receipt.operationId || '')
      || !String(receipt.conversationKey || '')
      || !Number(receipt.tabId) || !Number(receipt.windowId)) return false;
  try {
    const tab = await newChatLiveTab(receipt);
    if (RelayCore.conversationKey(String(tab.url || ''))
        !== String(receipt.conversationKey || '')) return false;
    const retired = await browserGateway.sendWithReceiver(Number(tab.id), {
      type: 'relay:retireExecution', relayId: receipt.operationId,
    });
    return retired?.ok === true && retired?.retired === true
      && retired?.relayId === receipt.operationId;
  } catch (_) {
    return false;
  }
}

// A create-and-send request can outlive the caller's bounded wait while the
// exact ChatGPT tab keeps generating.  A later result lookup may finish that
// receipt from the already-submitted tab, but it must never create a tab or
// submit the prompt again.  Only states at or beyond SUBMIT_INTENT are eligible
// and collectNewChatResult revalidates the exact tab/window/conversation/hash.
async function recoverPersistedNewChatResult(state, operationId) {
  const persisted = publicPersistedNewChatResult(state, operationId);
  if (persisted) {
    await retirePersistedNewChatExecution(
      state?.newChatReceipts?.[operationId] || null,
    );
    return persisted;
  }
  const receipt = state?.newChatReceipts?.[operationId] || null;
  if (!receipt) return null;
  if (!['SUBMIT_INTENT', 'SUBMITTED', 'SUBMIT_UNKNOWN'].includes(
    String(receipt.state || ''),
  )) return null;
  if (!Number(receipt.tabId) || !Number(receipt.windowId)
      || !/^[a-f0-9]{64}$/.test(String(receipt.textSha256 || ''))) return null;
  const recovered = await collectNewChatResult(receipt, Date.now() + 1000);
  return recovered?.state === 'RESULT_PERSISTED'
    ? publicNewChatResult(recovered, true) : null;
}

function newChatOperationId(value) {
  const operationId = String(value || '').trim();
  if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(operationId)) {
    throw new Error('NEW_CHAT_OPERATION_ID_INVALID');
  }
  return operationId;
}

function newChatText(value) {
  const text = String(value || '');
  if (!text || text.length > 12000) throw new Error('NEW_CHAT_TEXT_INVALID');
  return text;
}

async function newChatLiveTab(receipt) {
  const tab = await browserGateway.getExactTab(Number(receipt.tabId));
  if (!browserGateway.isChatTab(tab)
      || Number(tab.windowId) !== Number(receipt.windowId)) {
    throw new Error('NEW_CHAT_TAB_IDENTITY_MISMATCH');
  }
  return tab;
}

async function collectNewChatResult(receipt, deadline) {
  let lastError = '';
  while (Date.now() < deadline) {
    let tab;
    try {
      tab = await newChatLiveTab(receipt);
    } catch (error) {
      lastError = String(error?.message || error || 'NEW_CHAT_TAB_UNAVAILABLE');
      break;
    }
    const conversationKey = RelayCore.conversationKey(String(tab.url || ''));
    if (conversationKey) {
      try {
        const status = await browserGateway.sendWithReceiver(Number(tab.id), {
          type: 'relay:newChatStatus',
          relayId: receipt.operationId,
          textSha256: receipt.textSha256,
        });
        if (status?.ok === true && status?.submitted === true
            && String(status.conversationKey || '') === conversationKey) {
          const submitted = receipt.state === 'SUBMITTED' ? receipt : await writeNewChatReceipt(
            receipt.operationId,
            { ...receipt, state: 'SUBMITTED', conversationKey,
              stageTiming: { ...(receipt.stageTiming || {}),
                conversationCapturedAt: Date.now() } },
          );
          receipt = submitted;
          if (status.completed === true && typeof status.reply === 'string'
              && status.reply.trim()) {
            const reply = status.reply;
            const resultHash = await relaySha256(JSON.stringify([
              receipt.operationId, receipt.instanceId, receipt.sessionId,
              receipt.tabId, receipt.windowId, conversationKey,
              receipt.textSha256, reply,
            ]));
            const persisted = await writeNewChatReceipt(receipt.operationId, {
              ...receipt,
              state: 'RESULT_PERSISTED',
              conversationKey,
              reply,
              resultHash,
              stageTiming: { ...(receipt.stageTiming || {}), completedAt: Date.now() },
            });
            await retirePersistedNewChatExecution(persisted);
            return persisted;
          }
        } else if (status?.effectState === 'NOT_APPLIED') {
          lastError = String(status.error || 'NEW_CHAT_STATUS_NOT_APPLIED');
        }
      } catch (error) {
        lastError = String(error?.message || error || 'NEW_CHAT_STATUS_UNAVAILABLE');
      }
    }
    await new Promise((resolve) => setTimeout(resolve, conversationKey ? 500 : 200));
  }
  const pending = await writeNewChatReceipt(receipt.operationId, {
    ...receipt,
    state: receipt.state === 'SUBMIT_INTENT' ? 'SUBMIT_UNKNOWN' : receipt.state,
    error: lastError || 'NEW_CHAT_RESULT_TIMEOUT',
  });
  return pending;
}

async function sendNewChatAndAwaitResult(message) {
  await endpointSessionReady;
  const operationId = newChatOperationId(message.operationId || message.requestId);
  const text = newChatText(message.text);
  const requestedWindowId = Number(message.windowId);
  const timeoutMs = Math.max(15000, Math.min(360000,
    Number(message.responseTimeoutMs || 300000)));
  if (!Number.isSafeInteger(requestedWindowId) || requestedWindowId < 1) {
    throw new Error('NEW_CHAT_WINDOW_ID_INVALID');
  }
  const state = await loadState();
  const instanceId = String(state.settings.instanceId || '');
  if (String(message.instanceId || '') !== instanceId) {
    throw new Error('NEW_CHAT_INSTANCE_ID_MISMATCH');
  }
  const textSha256 = await relaySha256(text);
  const fingerprint = await relaySha256(JSON.stringify([
    instanceId, requestedWindowId, textSha256,
  ]));
  const existing = (await readNewChatReceipts())[operationId] || null;
  if (existing) {
    if (existing.fingerprint !== fingerprint) {
      throw new Error('NEW_CHAT_OPERATION_ID_REUSE_MISMATCH');
    }
    if (existing.state === 'RESULT_PERSISTED' || existing.state === 'NOT_APPLIED'
        || existing.state === 'SUBMIT_UNKNOWN' || existing.state === 'CREATE_UNKNOWN') {
      if (existing.state === 'RESULT_PERSISTED') {
        await retirePersistedNewChatExecution(existing);
      }
      return publicNewChatResult(existing, true);
    }
    if (!Number(existing.tabId)) {
      return publicNewChatResult(await writeNewChatReceipt(operationId, {
        ...existing, state: 'CREATE_UNKNOWN', error: 'NEW_CHAT_CREATE_RECEIPT_INCOMPLETE',
      }), true);
    }
    return publicNewChatResult(
      await collectNewChatResult(existing, Date.now() + timeoutMs), true,
    );
  }

  const beganAt = Date.now();
  let receipt = await writeNewChatReceipt(operationId, {
    command: 'new-chat-send', fingerprint, state: 'INTENT', instanceId,
    sessionId: endpointSessionId, requestedWindowId, textSha256,
    stageTiming: { beganAt },
  });
  const created = await getTabCreateAdapter().createTab({
    operationId, instanceId, sessionId: endpointSessionId,
    requestedWindowId, conversationKey: '',
  });
  if (created?.ok !== true || created?.state !== 'PENDING_UNBOUND'
      || !Number(created.tabId) || Number(created.windowId) !== requestedWindowId) {
    const failed = await writeNewChatReceipt(operationId, {
      ...receipt,
      state: created?.effectState === 'NOT_APPLIED' ? 'NOT_APPLIED' : 'CREATE_UNKNOWN',
      error: String(created?.error || 'NEW_CHAT_CREATE_UNVERIFIED'),
      stageTiming: { ...receipt.stageTiming, createFinishedAt: Date.now() },
    });
    return publicNewChatResult(failed);
  }
  receipt = await writeNewChatReceipt(operationId, {
    ...receipt,
    state: 'CREATED',
    sessionId: String(created.sessionId || endpointSessionId),
    tabId: Number(created.tabId),
    windowId: Number(created.windowId),
    stageTiming: { ...receipt.stageTiming, createFinishedAt: Date.now() },
  });

  // The durable SUBMIT_INTENT is written before the only activation attempt.
  // Any transport loss after this point is reconciled by the exact tab/UUID/DOM
  // status path below and is never repaired by submitting the prompt again.
  receipt = await writeNewChatReceipt(operationId, {
    ...receipt, state: 'SUBMIT_INTENT',
    stageTiming: { ...receipt.stageTiming, submitAttemptedAt: Date.now() },
  });
  try {
    const execution = await browserGateway.sendWithReceiver(receipt.tabId, {
      type: 'relay:newChatExecute', relayId: operationId,
      text, textSha256,
    });
    // A classified non-Chat surface is a terminal no-effect result.  Retain
    // its minimal evidence so callers can preserve the tab without trying to
    // submit into it again.  Other transport losses remain recoverable through
    // the exact tab/UUID/DOM path below.
    if (execution?.effectState === 'NOT_APPLIED' && execution?.submitted === false) {
      const failed = await writeNewChatReceipt(operationId, {
        ...receipt,
        state: 'NOT_APPLIED',
        surfaceKind: String(execution.surfaceKind || ''),
        surfaceEvidence: execution.surfaceEvidence && typeof execution.surfaceEvidence === 'object'
          ? execution.surfaceEvidence : null,
        error: String(execution.error || 'NEW_CHAT_SURFACE_NOT_APPLIED'),
        stageTiming: { ...receipt.stageTiming, surfaceClassifiedAt: Date.now() },
      });
      return publicNewChatResult(failed);
    }
  } catch (_) {
    // Expected when ChatGPT replaces the blank document with /c/<uuid>.
    // Exact DOM recovery below is the only authority after activation.
  }
  const completed = await collectNewChatResult(receipt, beganAt + timeoutMs);
  return publicNewChatResult(completed);
}
