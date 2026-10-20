(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserTabMoveContract = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const SCHEMA = 'rcc.browser.tab-move.receipt.v1';
  const STATES = Object.freeze({
    MOVED: 'MOVED',
    NOT_APPLIED: 'NOT_APPLIED',
    MOVE_UNKNOWN: 'MOVE_UNKNOWN',
  });

  function positiveInteger(value, code) {
    const number = Number(value);
    if (!Number.isSafeInteger(number) || number < 1) throw new Error(code);
    return number;
  }

  function normalizeIntent(value) {
    const intent = value || {};
    const operationId = String(intent.operationId || '').trim();
    if (!operationId) throw new Error('TAB_MOVE_OPERATION_ID_REQUIRED');
    const requestedIndex = Number(intent.requestedIndex);
    if (!Number.isSafeInteger(requestedIndex) || requestedIndex < -1) {
      throw new Error('TAB_MOVE_INDEX_INVALID');
    }
    return Object.freeze({
      operationId,
      tabId: positiveInteger(intent.tabId, 'TAB_MOVE_TAB_ID_INVALID'),
      expectedWindowId: positiveInteger(intent.expectedWindowId, 'TAB_MOVE_SOURCE_WINDOW_INVALID'),
      targetWindowId: positiveInteger(intent.targetWindowId, 'TAB_MOVE_TARGET_WINDOW_INVALID'),
      requestedIndex,
      conversationKey: String(intent.conversationKey || '').trim(),
      expectBlankConversation: intent.expectBlankConversation === true,
    });
  }

  function fingerprint(value) {
    const intent = normalizeIntent(value);
    return JSON.stringify([
      intent.tabId, intent.expectedWindowId, intent.targetWindowId, intent.requestedIndex,
      intent.conversationKey, intent.expectBlankConversation,
    ]);
  }

  function tabEvidence(tab) {
    if (!tab) return null;
    const id = Number(tab.id);
    const windowId = Number(tab.windowId);
    const index = Number(tab.index);
    return Object.freeze({
      tabId: Number.isSafeInteger(id) ? id : null,
      windowId: Number.isSafeInteger(windowId) ? windowId : null,
      index: Number.isSafeInteger(index) ? index : null,
    });
  }

  function receipt(value, state, details = {}) {
    const intent = normalizeIntent(value);
    if (!Object.values(STATES).includes(state)) throw new Error('TAB_MOVE_RECEIPT_STATE_INVALID');
    const effectState = state === STATES.MOVED ? 'APPLIED_CONFIRMED'
      : state === STATES.NOT_APPLIED ? 'NOT_APPLIED' : 'UNKNOWN';
    return Object.freeze({
      schema: SCHEMA,
      command: 'move-tab',
      operationId: intent.operationId,
      fingerprint: fingerprint(intent),
      ok: state === STATES.MOVED,
      state,
      effectState,
      retrySafe: false,
      moved: state === STATES.MOVED,
      tabId: intent.tabId,
      expectedWindowId: intent.expectedWindowId,
      targetWindowId: intent.targetWindowId,
      requestedIndex: intent.requestedIndex,
      before: tabEvidence(details.before),
      after: tabEvidence(details.after),
      error: state === STATES.MOVED ? undefined : String(details.error || state),
    });
  }

  return Object.freeze({ SCHEMA, STATES, normalizeIntent, fingerprint, receipt });
});
