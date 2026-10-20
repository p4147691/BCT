(() => {
  'use strict';

  const CHAT_HOST = /^(chatgpt\.com|chat\.openai\.com)$/i;
  const CONVERSATION_UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;

  function conversationKeyFromUrl(value) {
    try {
      const url = new URL(String(value || ''));
      if (!CHAT_HOST.test(url.hostname)) return '';
      const match = url.pathname.match(/^\/c\/([a-z0-9-]{8,64})(?:\/|$)/i);
      const key = String(match?.[1] || '').toLowerCase();
      return key === 'local-chatgpt' ? '' : key;
    } catch {
      return '';
    }
  }

  function conversationUuid(value) {
    const key = String(value || '').trim().toLowerCase();
    if (!CONVERSATION_UUID.test(key)) throw new Error('RCC_CORE_CONVERSATION_UUID_INVALID');
    return key;
  }

  // This is an observation result only. tab/window identifiers are returned
  // for the caller's immediate request and must never become a stored route.
  function resolveExactConversation(tabs, conversationValue) {
    const conversationKey = conversationUuid(conversationValue);
    const matches = (Array.isArray(tabs) ? tabs : [])
      .filter((tab) => conversationKeyFromUrl(tab?.url) === conversationKey)
      .map((tab) => Object.freeze({
        tabId: Number.isInteger(tab?.id) ? tab.id : null,
        windowId: Number.isInteger(tab?.windowId) ? tab.windowId : null,
        conversationKey,
      }));
    if (!matches.length) {
      return Object.freeze({ status: 'MISSING', conversationKey, matches: Object.freeze([]) });
    }
    if (matches.length !== 1) {
      return Object.freeze({ status: 'AMBIGUOUS', conversationKey, matches: Object.freeze(matches) });
    }
    return Object.freeze({ status: 'EXACT', conversationKey, match: matches[0] });
  }

  const api = Object.freeze({ conversationKeyFromUrl, conversationUuid, resolveExactConversation });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.RccCoreIdentity = api;
})();
