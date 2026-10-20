(() => {
  'use strict';

  const Identity = typeof module !== 'undefined' && module.exports
    ? require('./identity.js') : globalThis.RccCoreIdentity;
  if (!Identity) throw new Error('RCC_CORE_IDENTITY_REQUIRED');

  const STATUS = Object.freeze({
    CONNECTED: 'CONNECTED',
    MISSING: 'MISSING',
    AMBIGUOUS: 'AMBIGUOUS',
    BUSY: 'BUSY',
    RECEIVER_UNKNOWN: 'RECEIVER_UNKNOWN',
    PROTOCOL_MISMATCH: 'PROTOCOL_MISMATCH',
  });

  function endpointForTab(endpoints, tabId) {
    const candidates = (Array.isArray(endpoints) ? endpoints : [])
      .filter((endpoint) => Number(endpoint?.tabId) === Number(tabId));
    return candidates.length === 1 ? candidates[0] : null;
  }

  // A receiver absence is deliberately distinct from MISSING. Existing RCC
  // may inject its receiver; the future Core must decide that explicitly and
  // never silently treat a different tab as the same conversation.
  function inspectConversation(tabs, endpoints, conversationValue) {
    const resolved = Identity.resolveExactConversation(tabs, conversationValue);
    if (resolved.status === 'MISSING') {
      return Object.freeze({ status: STATUS.MISSING, conversationKey: resolved.conversationKey });
    }
    if (resolved.status === 'AMBIGUOUS') {
      return Object.freeze({
        status: STATUS.AMBIGUOUS,
        conversationKey: resolved.conversationKey,
        matchCount: resolved.matches.length,
      });
    }
    const endpoint = endpointForTab(endpoints, resolved.match.tabId);
    if (!endpoint) {
      return Object.freeze({
        status: STATUS.RECEIVER_UNKNOWN,
        conversationKey: resolved.conversationKey,
        tabId: resolved.match.tabId,
      });
    }
    if (String(endpoint.conversationKey || '').toLowerCase() !== resolved.conversationKey) {
      return Object.freeze({
        status: STATUS.PROTOCOL_MISMATCH,
        conversationKey: resolved.conversationKey,
        tabId: resolved.match.tabId,
      });
    }
    if (String(endpoint.presence || '') !== 'OPEN') {
      return Object.freeze({
        status: STATUS.PROTOCOL_MISMATCH,
        conversationKey: resolved.conversationKey,
        tabId: resolved.match.tabId,
      });
    }
    if (endpoint.generating === true) {
      return Object.freeze({
        status: STATUS.BUSY,
        conversationKey: resolved.conversationKey,
        tabId: resolved.match.tabId,
      });
    }
    return Object.freeze({
      status: STATUS.CONNECTED,
      conversationKey: resolved.conversationKey,
      tabId: resolved.match.tabId,
    });
  }

  function inspectPair(tabs, endpoints, firstConversation, secondConversation) {
    const first = inspectConversation(tabs, endpoints, firstConversation);
    const second = inspectConversation(tabs, endpoints, secondConversation);
    return Object.freeze({ first, second, connected: first.status === STATUS.CONNECTED && second.status === STATUS.CONNECTED });
  }

  const api = Object.freeze({ STATUS, inspectConversation, inspectPair });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.RccCoreState = api;
})();
