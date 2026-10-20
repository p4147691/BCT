(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserTabReloadContract = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const SCHEMA = 'rcc.browser.tab-reload.receipt.v1';
  const STATES = Object.freeze({
    RELOADED_CONFIRMED: 'RELOADED_CONFIRMED',
    NOT_APPLIED: 'NOT_APPLIED',
    RELOAD_UNKNOWN: 'RELOAD_UNKNOWN',
  });

  function positiveInteger(value, code) {
    const number = Number(value);
    if (!Number.isSafeInteger(number) || number < 1) throw new Error(code);
    return number;
  }

  function normalizeIntent(value) {
    const intent = value || {};
    const operationId = String(intent.operationId || '').trim();
    const instanceId = String(intent.instanceId || '').trim();
    const sessionId = String(intent.sessionId || '').trim();
    const targetRole = String(intent.targetRole || '').trim();
    const conversationKey = String(intent.conversationKey || '').trim();
    if (!operationId) throw new Error('TAB_RELOAD_OPERATION_ID_REQUIRED');
    if (!instanceId || !sessionId) throw new Error('TAB_RELOAD_ENDPOINT_IDENTITY_REQUIRED');
    if (!targetRole) throw new Error('TAB_RELOAD_TARGET_ROLE_REQUIRED');
    if (!/^[a-z0-9-]{8,64}$/i.test(conversationKey)) {
      throw new Error('TAB_RELOAD_CONVERSATION_KEY_INVALID');
    }
    return Object.freeze({
      operationId,
      instanceId,
      sessionId,
      targetRole,
      tabId: positiveInteger(intent.tabId, 'TAB_RELOAD_TAB_ID_INVALID'),
      conversationKey,
    });
  }

  function fingerprint(value) {
    const intent = normalizeIntent(value);
    return JSON.stringify([
      intent.instanceId, intent.sessionId, intent.targetRole,
      intent.tabId, intent.conversationKey,
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
    if (!Object.values(STATES).includes(state)) throw new Error('TAB_RELOAD_RECEIPT_STATE_INVALID');
    const confirmed = state === STATES.RELOADED_CONFIRMED;
    return Object.freeze({
      schema: SCHEMA,
      command: 'reload-tab',
      operationId: intent.operationId,
      fingerprint: fingerprint(intent),
      ok: confirmed,
      state,
      effectState: confirmed ? 'APPLIED_CONFIRMED'
        : state === STATES.NOT_APPLIED ? 'NOT_APPLIED' : 'UNKNOWN',
      retrySafe: false,
      reloaded: confirmed,
      instanceId: intent.instanceId,
      sessionId: intent.sessionId,
      targetRole: intent.targetRole,
      tabId: intent.tabId,
      conversationKey: intent.conversationKey,
      before: tabEvidence(details.before),
      after: tabEvidence(details.after),
      navigationCompleted: details.navigationCompleted === true,
      receiverReady: details.receiverReady === true,
      error: confirmed ? undefined : String(details.error || state),
    });
  }

  return Object.freeze({ SCHEMA, STATES, normalizeIntent, fingerprint, receipt });
});
