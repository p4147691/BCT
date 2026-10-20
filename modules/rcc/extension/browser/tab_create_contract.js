(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserTabCreateContract = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const SCHEMA = 'rcc.browser.tab-create.receipt.v1';
  const STATES = Object.freeze({
    PENDING_UNBOUND: 'PENDING_UNBOUND',
    CREATED_CONFIRMED: 'CREATED_CONFIRMED',
    NOT_APPLIED: 'NOT_APPLIED',
    CREATE_UNKNOWN: 'CREATE_UNKNOWN',
  });

  function optionalPositiveInteger(value) {
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    if (!Number.isSafeInteger(number) || number < 1) throw new Error('TAB_CREATE_WINDOW_ID_INVALID');
    return number;
  }

  function normalizeIntent(value) {
    const intent = value || {};
    const operationId = String(intent.operationId || '').trim();
    const instanceId = String(intent.instanceId || '').trim();
    const sessionId = String(intent.sessionId || '').trim();
    const conversationKey = String(intent.conversationKey || '').trim();
    if (!operationId) throw new Error('TAB_CREATE_OPERATION_ID_REQUIRED');
    if (!instanceId || !sessionId) throw new Error('TAB_CREATE_ENDPOINT_IDENTITY_REQUIRED');
    if (conversationKey && !/^[a-z0-9-]{8,64}$/i.test(conversationKey)) {
      throw new Error('TAB_CREATE_CONVERSATION_KEY_INVALID');
    }
    return Object.freeze({
      operationId,
      instanceId,
      sessionId,
      requestedWindowId: optionalPositiveInteger(intent.requestedWindowId),
      conversationKey,
      url: conversationKey ? `https://chatgpt.com/c/${conversationKey}` : 'https://chatgpt.com/',
      active: false,
    });
  }

  function fingerprint(value) {
    const intent = normalizeIntent(value);
    return JSON.stringify([intent.requestedWindowId, intent.url, intent.active]);
  }

  function tabEvidence(tab) {
    if (!tab) return null;
    const tabId = Number(tab.id);
    const windowId = Number(tab.windowId);
    const index = Number(tab.index);
    return Object.freeze({
      tabId: Number.isSafeInteger(tabId) ? tabId : null,
      windowId: Number.isSafeInteger(windowId) ? windowId : null,
      index: Number.isSafeInteger(index) ? index : null,
    });
  }

  function receipt(value, state, details = {}) {
    const intent = normalizeIntent(value);
    if (!Object.values(STATES).includes(state)) throw new Error('TAB_CREATE_RECEIPT_STATE_INVALID');
    const confirmed = state === STATES.PENDING_UNBOUND || state === STATES.CREATED_CONFIRMED;
    const evidence = tabEvidence(details.tab);
    const bindingState = intent.conversationKey ? 'TARGET_CONFIRMED' : 'PENDING_UNBOUND';
    return Object.freeze({
      schema: SCHEMA,
      command: 'create-chat-tab',
      operationId: intent.operationId,
      fingerprint: fingerprint(intent),
      ok: confirmed,
      state,
      effectState: confirmed ? 'APPLIED_CONFIRMED'
        : state === STATES.NOT_APPLIED ? 'NOT_APPLIED' : 'UNKNOWN',
      retrySafe: false,
      created: confirmed ? true : details.createdObserved === true,
      tabId: evidence?.tabId ?? null,
      windowId: evidence?.windowId ?? intent.requestedWindowId,
      instanceId: intent.instanceId,
      sessionId: intent.sessionId,
      conversationKey: intent.conversationKey,
      bindingState,
      pending: !intent.conversationKey,
      unbound: !intent.conversationKey,
      creationReceipt: confirmed ? Object.freeze({
        operationId: intent.operationId,
        tabId: evidence.tabId,
        windowId: evidence.windowId,
        instanceId: intent.instanceId,
        sessionId: intent.sessionId,
        conversationKey: intent.conversationKey,
        bindingState,
      }) : null,
      error: confirmed ? undefined : String(details.error || state),
    });
  }

  return Object.freeze({ SCHEMA, STATES, normalizeIntent, fingerprint, receipt });
});
