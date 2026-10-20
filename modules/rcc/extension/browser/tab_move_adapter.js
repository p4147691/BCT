(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserTabMoveAdapter = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi, contract, identity) {
    if (typeof chromeApi?.tabs?.get !== 'function'
        || typeof chromeApi?.tabs?.query !== 'function'
        || typeof chromeApi?.tabs?.move !== 'function') {
      throw new Error('RCC_BROWSER_TAB_MOVE_API_REQUIRED');
    }
    if (!contract?.STATES || typeof contract.normalizeIntent !== 'function'
        || typeof contract.receipt !== 'function') {
      throw new Error('RCC_BROWSER_TAB_MOVE_CONTRACT_REQUIRED');
    }
    if (typeof identity?.isChatTab !== 'function'
        || typeof identity?.conversationKey !== 'function') {
      throw new Error('RCC_BROWSER_TAB_MOVE_IDENTITY_REQUIRED');
    }

    function identityMatches(tab, intent) {
      if (!tab || Number(tab.id) !== intent.tabId
          || Number(tab.windowId) !== intent.expectedWindowId
          || !identity.isChatTab(tab)) return false;
      const liveKey = String(identity.conversationKey(tab.url || '') || '');
      if (intent.expectBlankConversation) return !liveKey;
      return !!intent.conversationKey && liveKey === intent.conversationKey;
    }

    async function move(value) {
      const intent = contract.normalizeIntent(value);
      let before = null;
      try {
        before = await chromeApi.tabs.get(intent.tabId);
        if (!identityMatches(before, intent)) {
          return contract.receipt(intent, contract.STATES.NOT_APPLIED, {
            before, error: 'TAB_MOVE_SOURCE_IDENTITY_MISMATCH',
          });
        }
        const targetTabs = await chromeApi.tabs.query({ windowId: intent.targetWindowId });
        const sameWindow = intent.expectedWindowId === intent.targetWindowId;
        if (sameWindow && !targetTabs.some((tab) => Number(tab.id) === intent.tabId)) {
          return contract.receipt(intent, contract.STATES.NOT_APPLIED, {
            before, error: 'TAB_MOVE_SOURCE_MISSING_FROM_WINDOW',
          });
        }
        const maxIndex = sameWindow ? Math.max(0, targetTabs.length - 1) : targetTabs.length;
        if (intent.requestedIndex !== -1 && intent.requestedIndex > maxIndex) {
          return contract.receipt(intent, contract.STATES.NOT_APPLIED, {
            before, error: 'TAB_MOVE_INDEX_OUT_OF_RANGE',
          });
        }
      } catch (error) {
        return contract.receipt(intent, contract.STATES.NOT_APPLIED, {
          before, error: String(error?.message || error || 'TAB_MOVE_PRECHECK_FAILED'),
        });
      }

      try {
        await chromeApi.tabs.move(intent.tabId, {
          windowId: intent.targetWindowId,
          index: intent.requestedIndex,
        });
        const after = await chromeApi.tabs.get(intent.tabId);
        const movedIdentity = { ...intent, expectedWindowId: intent.targetWindowId };
        if (!identityMatches(after, movedIdentity)) {
          return contract.receipt(intent, contract.STATES.MOVE_UNKNOWN, {
            before, after, error: 'TAB_MOVE_POSTCONDITION_UNPROVEN',
          });
        }
        return contract.receipt(intent, contract.STATES.MOVED, { before, after });
      } catch (error) {
        return contract.receipt(intent, contract.STATES.MOVE_UNKNOWN, {
          before, error: String(error?.message || error || 'TAB_MOVE_EFFECT_UNKNOWN'),
        });
      }
    }

    return Object.freeze({ move });
  }

  return Object.freeze({ create });
});
