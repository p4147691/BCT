(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserWindowCreateContract = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const SCHEMA = 'rcc.browser.window-create.receipt.v1';
  const STATES = Object.freeze({
    PENDING_UNBOUND: 'PENDING_UNBOUND',
    CREATE_UNKNOWN: 'CREATE_UNKNOWN',
  });

  function normalizeIntent(value) {
    const intent = value || {};
    const operationId = String(intent.operationId || '').trim();
    const instanceId = String(intent.instanceId || '').trim();
    const sessionId = String(intent.sessionId || '').trim();
    const conversationKey = String(intent.conversationKey || '').trim();
    if (!operationId) throw new Error('WINDOW_CREATE_OPERATION_ID_REQUIRED');
    if (!instanceId || !sessionId) throw new Error('WINDOW_CREATE_ENDPOINT_IDENTITY_REQUIRED');
    if (conversationKey) throw new Error('WINDOW_CREATE_CONVERSATION_KEY_FORBIDDEN');
    return Object.freeze({
      operationId,
      instanceId,
      sessionId,
      url: 'https://chatgpt.com/',
      type: 'normal',
      focused: true,
      conversationKey: '',
      bindingState: 'PENDING_UNBOUND',
    });
  }

  function fingerprint(value) {
    const intent = normalizeIntent(value);
    return JSON.stringify([
      intent.instanceId, intent.sessionId, intent.url, intent.type, intent.focused,
    ]);
  }

  function positiveIntegerOrNull(value) {
    const number = Number(value);
    return Number.isSafeInteger(number) && number > 0 ? number : null;
  }

  function receipt(value, state, details = {}) {
    const intent = normalizeIntent(value);
    if (!Object.values(STATES).includes(state)) throw new Error('WINDOW_CREATE_RECEIPT_STATE_INVALID');
    const confirmed = state === STATES.PENDING_UNBOUND;
    const windowId = positiveIntegerOrNull(details.window?.id ?? details.windowId);
    const tabId = positiveIntegerOrNull(details.tab?.id ?? details.tabId);
    const windowState = confirmed
      ? String(details.window?.state || details.windowState || 'normal').toUpperCase()
      : 'UNKNOWN';
    return Object.freeze({
      schema: SCHEMA,
      command: 'create-chat-window',
      operationId: intent.operationId,
      fingerprint: fingerprint(intent),
      ok: confirmed,
      state,
      effectState: confirmed ? 'APPLIED_CONFIRMED' : 'UNKNOWN',
      retrySafe: false,
      created: confirmed || details.createdObserved === true,
      instanceId: intent.instanceId,
      sessionId: intent.sessionId,
      url: intent.url,
      conversationKey: '',
      bindingState: intent.bindingState,
      windowId,
      tabId,
      windowState,
      tabPresence: confirmed ? 'OPEN' : 'UNKNOWN',
      creationReceipt: confirmed ? Object.freeze({
        operationId: intent.operationId,
        windowId,
        tabId,
        url: intent.url,
        instanceId: intent.instanceId,
        sessionId: intent.sessionId,
        conversationKey: '',
        bindingState: intent.bindingState,
        windowState,
        tabPresence: 'OPEN',
      }) : null,
      error: confirmed ? undefined : 'CREATE_UNKNOWN',
    });
  }

  return Object.freeze({ SCHEMA, STATES, normalizeIntent, fingerprint, receipt });
});
