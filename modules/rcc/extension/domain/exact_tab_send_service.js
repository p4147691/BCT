// One explicit message to one already-open Chrome ChatGPT tab.  This is not a
// discovery or browser-management route: tabId/sessionId are fenced again
// immediately before the only UI action.  windowId is observed context only:
// moving the same tab to another Chrome window must not retarget or block it.
const EXACT_TAB_SEND_RECEIPTS_KEY = 'exactTabSendReceiptsV1';
let exactTabSendMutation = Promise.resolve();

function exactTabSendOperationId(value) {
  const id = String(value || '').trim();
  if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(id)) throw new Error('EXACT_TAB_OPERATION_ID_INVALID');
  return id;
}

function exactTabSendText(value) {
  const text = String(value || '');
  if (!text || text.length > 12000) throw new Error('EXACT_TAB_TEXT_INVALID');
  return text;
}

async function readExactTabSendReceipts() {
  const data = await stateRepository.getLocal(EXACT_TAB_SEND_RECEIPTS_KEY);
  const receipts = data[EXACT_TAB_SEND_RECEIPTS_KEY];
  return receipts && typeof receipts === 'object' ? receipts : {};
}

async function writeExactTabSendReceipt(operationId, receipt) {
  const task = exactTabSendMutation.then(async () => {
    const receipts = await readExactTabSendReceipts();
    receipts[operationId] = { ...receipt, operationId, updatedAt: Date.now() };
    const retained = Object.entries(receipts)
      .sort((left, right) => Number(right[1]?.updatedAt || 0) - Number(left[1]?.updatedAt || 0))
      .slice(0, 32);
    await stateRepository.setLocal({ [EXACT_TAB_SEND_RECEIPTS_KEY]: Object.fromEntries(retained) });
    return receipts[operationId];
  });
  exactTabSendMutation = task.catch(() => {});
  return task;
}

function publicExactTabSendResult(receipt, replayed = false) {
  const state = String(receipt?.state || 'UNKNOWN');
  const submitted = state === 'SUBMITTED';
  return {
    ok: submitted,
    command: 'send-to-tab',
    operationId: String(receipt?.operationId || ''),
    state,
    effectState: submitted ? 'APPLIED_CONFIRMED'
      : state === 'NOT_APPLIED' ? 'NOT_APPLIED' : 'UNKNOWN',
    ambiguous: !submitted && state !== 'NOT_APPLIED',
    replayed,
    instanceId: String(receipt?.instanceId || ''),
    sessionId: String(receipt?.sessionId || ''),
    tabId: Number(receipt?.tabId) || null,
    windowId: Number(receipt?.windowId) || null,
    conversationKey: String(receipt?.conversationKey || ''),
    submitted,
    error: submitted ? '' : String(receipt?.error || state),
  };
}

function exactTabIsBlankChat(url, conversationKey) {
  return !conversationKey
    && /^https:\/\/(chatgpt\.com|chat\.openai\.com)\/?(?:[?#].*)?$/i.test(String(url || ''));
}

function exactTabDelay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// The first ChatGPT message can replace the blank document before its original
// receiver replies.  Never submit again: recover only through the same tabId,
// the post-navigation UUID, and the persisted exact-user-turn proof.
// Allow delayed provider route/user-turn mounting before declaring UNKNOWN.
// Read-only status probes never resubmit; absent exact proof remains UNKNOWN.
async function recoverExactBlankTabSubmission(tabId, relayId, textSha256, deadline) {
  while (Date.now() < deadline) {
    try {
      const tab = await browserGateway.getExactTab(tabId);
      if (!browserGateway.isChatTab(tab)) return null;
      const conversationKey = RelayCore.conversationKey(String(tab?.url || '')).toLowerCase();
      if (conversationKey) {
        const status = await browserGateway.sendWithReceiver(tabId, {
          type: 'relay:newChatStatus', relayId, textSha256,
        });
        if (status?.ok === true && status?.submitted === true
            && String(status?.relayId || '') === relayId
            && String(status?.conversationKey || '').toLowerCase() === conversationKey) {
          return { ...status, conversationKey };
        }
        if (status?.effectState === 'NOT_APPLIED') return null;
      }
    } catch (_) {
      // The blank document is expected to disappear during navigation.  The
      // bounded status probe is the only recovery action and never submits.
    }
    await exactTabDelay(200);
  }
  return null;
}

async function sendToExactExistingTab(message, requestId) {
  await endpointSessionReady;
  const operationId = exactTabSendOperationId(message?.operationId || requestId);
  const instanceId = String(message?.instanceId || '').trim();
  const sessionId = String(message?.sessionId || '').trim();
  const workId = String(message?.workId || '').trim();
  const tabId = Number(message?.tabId);
  const windowId = Number(message?.windowId);
  const requestedKey = String(message?.conversationKey || '').trim().toLowerCase();
  const text = exactTabSendText(message?.text);
  if (!instanceId || !/^[a-f0-9]{32}$/i.test(sessionId)
      || !workId || !Number.isSafeInteger(tabId) || tabId < 1
      || !Number.isSafeInteger(windowId) || windowId < 1
      || (requestedKey && !/^[a-f0-9-]{8,64}$/i.test(requestedKey))) {
    throw new Error('EXACT_TAB_ARGUMENT_INVALID');
  }
  const state = await loadState();
  if (instanceId !== String(state.settings?.instanceId || '')
      || sessionId !== String(endpointSessionId || '')) {
    throw new Error('EXACT_TAB_SESSION_MISMATCH');
  }
  const tab = await browserGateway.getExactTab(tabId);
  const liveKey = RelayCore.conversationKey(String(tab?.url || '')).toLowerCase();
  const blank = exactTabIsBlankChat(tab?.url, liveKey);
  if (!browserGateway.isChatTab(tab)
      || (!blank && (!requestedKey || liveKey !== requestedKey))
      || (blank && requestedKey)) {
    return publicExactTabSendResult({ operationId, instanceId, sessionId, tabId, windowId,
      conversationKey: liveKey, state: 'NOT_APPLIED', error: 'EXACT_TAB_IDENTITY_MISMATCH' });
  }
  const textSha256 = await relaySha256(text);
  const fingerprint = await relaySha256(JSON.stringify([
    instanceId, sessionId, workId, tabId, liveKey, textSha256,
  ]));
  const receipts = await readExactTabSendReceipts();
  const existing = receipts[operationId];
  if (existing) {
    if (String(existing.fingerprint || '') !== fingerprint) {
      throw new Error('EXACT_TAB_OPERATION_ID_REUSE_MISMATCH');
    }
    return publicExactTabSendResult(existing, true);
  }
  const intent = await writeExactTabSendReceipt(operationId, {
    command: 'send-to-tab', fingerprint, state: 'INTENT', instanceId, sessionId,
    workId, tabId, windowId: Number(tab.windowId), requestedWindowId: windowId,
    conversationKey: liveKey, textSha256,
  });
  let ack;
  let dispatchError = '';
  try {
    ack = blank
      ? await browserGateway.sendWithReceiver(tabId, {
        type: 'relay:newChatExecute', relayId: operationId, text, textSha256,
      })
      : await browserGateway.sendWithReceiver(tabId, {
        type: 'relay:simpleExecute', relayId: operationId,
        conversationKey: liveKey, text,
      });
  } catch (error) {
    dispatchError = String(error?.message || error || 'EXACT_TAB_TRANSPORT_UNKNOWN');
  }
  if (blank && !(ack?.ok === true && ack?.submitted === true
      && String(ack?.relayId || '') === operationId)) {
    const recovered = await recoverExactBlankTabSubmission(
      tabId, operationId, textSha256, Date.now() + 25000,
    );
    if (recovered) ack = recovered;
  }
  if (!ack && dispatchError) {
    return publicExactTabSendResult(await writeExactTabSendReceipt(operationId, {
      ...intent, state: 'UNKNOWN', error: dispatchError,
    }));
  }
  const submitted = ack?.ok === true && ack?.submitted === true
    && String(ack?.relayId || '') === operationId
    && (blank || String(ack?.conversationKey || '').toLowerCase() === liveKey);
  if (submitted) {
    return publicExactTabSendResult(await writeExactTabSendReceipt(operationId, {
      ...intent, state: 'SUBMITTED', conversationKey: String(ack?.conversationKey || liveKey || ''),
    }));
  }
  const notApplied = ack?.effectState === 'NOT_APPLIED' && ack?.submitted === false;
  return publicExactTabSendResult(await writeExactTabSendReceipt(operationId, {
    ...intent, state: notApplied ? 'NOT_APPLIED' : 'UNKNOWN',
    error: String(ack?.error || dispatchError || 'EXACT_TAB_ACK_UNVERIFIED'),
  }));
}
