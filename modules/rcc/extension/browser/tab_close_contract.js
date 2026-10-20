(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserTabCloseContract = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const SCHEMA = 'rcc.browser.tab-close.receipt.v1';
  const STATES = Object.freeze({
    CLOSED_CONFIRMED: 'CLOSED_CONFIRMED',
    NOT_APPLIED: 'NOT_APPLIED',
    CLOSE_UNKNOWN: 'CLOSE_UNKNOWN',
  });

  function positiveInteger(value, code) {
    const number = Number(value);
    if (!Number.isSafeInteger(number) || number < 1) throw new Error(code);
    return number;
  }

  function optionalPositiveInteger(value) {
    if (value === null || value === undefined || value === '') return null;
    return positiveInteger(value, 'TAB_CLOSE_WINDOW_ID_INVALID');
  }

  function normalizeIntent(value) {
    const intent = value || {};
    const operationId = String(intent.operationId || '').trim();
    const instanceId = String(intent.instanceId || '').trim();
    const sessionId = String(intent.sessionId || '').trim();
    const conversationKey = String(intent.conversationKey || '').trim();
    if (!operationId) throw new Error('TAB_CLOSE_OPERATION_ID_REQUIRED');
    if (!instanceId || !sessionId) throw new Error('TAB_CLOSE_ENDPOINT_IDENTITY_REQUIRED');
    if (!/^[a-z0-9-]{8,64}$/i.test(conversationKey)) {
      throw new Error('TAB_CLOSE_CONVERSATION_KEY_INVALID');
    }
    return Object.freeze({
      operationId,
      instanceId,
      sessionId,
      tabId: positiveInteger(intent.tabId, 'TAB_CLOSE_TAB_ID_INVALID'),
      expectedWindowId: optionalPositiveInteger(intent.expectedWindowId),
      conversationKey,
    });
  }

  function fingerprint(value) {
    const intent = normalizeIntent(value);
    return JSON.stringify([
      intent.instanceId, intent.sessionId, intent.tabId,
      intent.expectedWindowId, intent.conversationKey,
    ]);
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
    if (!Object.values(STATES).includes(state)) throw new Error('TAB_CLOSE_RECEIPT_STATE_INVALID');
    const confirmed = state === STATES.CLOSED_CONFIRMED;
    return Object.freeze({
      schema: SCHEMA,
      command: 'close-conversation-tab',
      operationId: intent.operationId,
      fingerprint: fingerprint(intent),
      ok: confirmed,
      state,
      effectState: confirmed ? 'APPLIED_CONFIRMED'
        : state === STATES.NOT_APPLIED ? 'NOT_APPLIED' : 'UNKNOWN',
      retrySafe: false,
      closed: confirmed,
      tabId: intent.tabId,
      expectedWindowId: intent.expectedWindowId,
      instanceId: intent.instanceId,
      sessionId: intent.sessionId,
      conversationKey: intent.conversationKey,
      before: tabEvidence(details.before),
      after: tabEvidence(details.after),
      tabPresence: confirmed ? 'ABSENT'
        : state === STATES.NOT_APPLIED ? 'UNCHANGED_OR_ABSENT' : 'UNKNOWN',
      error: confirmed ? undefined : String(details.error || state),
    });
  }

  return Object.freeze({ SCHEMA, STATES, normalizeIntent, fingerprint, receipt });
});
